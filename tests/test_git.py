"""Git panel (core/git_ops.py, core/credentials.py, /api/git/*) on throw-away repositories in support.TMP.
The real project repository and the real credentials file are never touched."""
import os
import stat
import subprocess
import tempfile
import time
import unittest

from tests.support import TMP, client, config  # noqa: F401  (support first)
from core import credentials, git_ops

TOKEN = 'ghp_TESTtoken1234567890abcdef'


def git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='T', GIT_AUTHOR_EMAIL='t@e.x', GIT_COMMITTER_NAME='T', GIT_COMMITTER_EMAIL='t@e.x')
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout


class GitRepo(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(dir=TMP)
        self.origin = os.path.join(self.base, 'origin.git')
        self.work = os.path.join(self.base, 'work')
        git(self.base, 'init', '-q', '--bare', '-b', 'main', self.origin)
        git(self.base, 'clone', '-q', self.origin, self.work)
        git(self.work, 'config', 'user.name', 'Tester')
        git(self.work, 'config', 'user.email', 'tester@example.com')
        self._write('README.md', 'hello\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-q', '-m', 'init')
        git(self.work, 'push', '-q', '-u', 'origin', 'main')
        self._saved = (config.CFG['target_dir'], config.CFG['help_dir'])
        config.CFG['target_dir'] = self.work
        self.c = client(logged_in=True)
        credentials.set_git('', '')

    def tearDown(self):
        config.CFG['target_dir'], config.CFG['help_dir'] = self._saved

    def _write(self, rel, text):
        full = os.path.join(self.work, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(text)

    def post(self, action, **body):
        body.setdefault('repo', 'project')
        return self.c.post('/api/git/' + action, json=body)

    # ── basics ──────────────────────────────────────────────

    def test_status_and_commit_selected_files(self):
        self._write('a.txt', 'a\n')
        self._write('b.txt', 'b\n')
        self._write('README.md', 'changed\n')
        st = self.c.get('/api/git/status?repo=project').get_json()
        files = {f['path']: f['kind'] for f in st['status']['files']}
        self.assertEqual(files, {'README.md': 'modified', 'a.txt': 'untracked', 'b.txt': 'untracked'})
        self.assertEqual(st['status']['branch'], 'main')
        r = self.post('commit', message='add a', paths=['a.txt', 'README.md'])
        self.assertEqual(r.status_code, 200, r.get_json())
        left = [f['path'] for f in r.get_json()['overview']['status']['files']]
        self.assertEqual(left, ['b.txt'])
        self.assertEqual(r.get_json()['overview']['status']['ahead'], 1)
        self.assertIn('add a', git(self.work, 'log', '-1', '--pretty=%s'))

    def test_commit_to_new_branch_and_push_sets_upstream(self):
        self._write('f.txt', 'x\n')
        r = self.post('commit', message='feature', new_branch='feature/x', push=True)
        self.assertEqual(r.status_code, 200, r.get_json())
        st = r.get_json()['overview']['status']
        self.assertEqual((st['branch'], st['upstream'], st['ahead']), ('feature/x', 'origin/feature/x', 0))
        self.assertIn('feature/x', git(self.origin, 'branch'))

    def test_pull_and_branches(self):
        other = os.path.join(self.base, 'other')
        git(self.base, 'clone', '-q', self.origin, other)
        with open(os.path.join(other, 'n.txt'), 'w') as f:
            f.write('n\n')
        git(other, 'add', '.')
        git(other, 'commit', '-q', '-m', 'remote change')
        git(other, 'push', '-q')
        self.assertEqual(self.post('fetch').get_json()['overview']['status']['behind'], 1)
        r = self.post('pull', mode='ff').get_json()
        self.assertEqual(r['overview']['status']['behind'], 0)
        self.assertTrue(os.path.exists(os.path.join(self.work, 'n.txt')))
        self.assertEqual(self.post('branch', name='dev').get_json()['overview']['status']['branch'], 'dev')
        self.assertEqual(self.post('checkout', branch='main').get_json()['overview']['status']['branch'], 'main')
        r = self.post('branch_delete', branch='dev').get_json()
        self.assertNotIn('dev', [b['name'] for b in r['overview']['branches']])

    def test_validation(self):
        self.assertEqual(self.post('branch', name='-x').status_code, 400)
        self.assertEqual(self.post('branch', name='a..b').status_code, 400)
        self.assertEqual(self.post('commit', message='').status_code, 400)
        self.assertEqual(self.post('commit', message='m').status_code, 400)                     # nothing to commit
        self.assertEqual(self.post('discard', paths=['../etc/passwd']).status_code, 400)
        self.assertEqual(self.post('commit', message='m', paths=['--help']).status_code, 400)
        self.assertEqual(self.c.get('/api/git/status?repo=nope').status_code, 404)
        self.assertEqual(self.post('fix', id='nope').status_code, 404)

    def test_discard(self):
        self._write('README.md', 'dirty\n')
        self._write('new.txt', 'new\n')
        r = self.post('discard', paths=['README.md', 'new.txt']).get_json()
        self.assertEqual(r['overview']['status']['files'], [])
        self.assertFalse(os.path.exists(os.path.join(self.work, 'new.txt')))

    # ── problems & fixes ────────────────────────────────────

    def test_diverged_and_reset_keeps_backup(self):
        other = os.path.join(self.base, 'other')
        git(self.base, 'clone', '-q', self.origin, other)
        with open(os.path.join(other, 'r.txt'), 'w') as f:
            f.write('r\n')
        git(other, 'add', '.')
        git(other, 'commit', '-q', '-m', 'remote')
        git(other, 'push', '-q')
        self._write('l.txt', 'l\n')
        git(self.work, 'add', '.')
        git(self.work, 'commit', '-q', '-m', 'local')
        git(self.work, 'fetch', '-q')
        self._write('README.md', 'uncommitted\n')
        ids = [p['id'] for p in self.c.get('/api/git/status?repo=project').get_json()['problems']]
        self.assertIn('diverged', ids)
        r = self.post('reset').get_json()
        st = r['overview']['status']
        self.assertEqual((st['ahead'], st['behind'], st['files']), (0, 0, []))
        backups = [b['name'] for b in r['overview']['branches'] if b['name'].startswith('backup/')]
        self.assertEqual(len(backups), 1)
        self.assertIn('local', git(self.work, 'log', '-1', '--pretty=%s', backups[0]))
        self.assertIn('panel backup', git(self.work, 'stash', 'list'))

    def test_fixes(self):
        git(self.work, 'remote', 'set-url', 'origin', 'https://user:secret123@example.com/r.git')
        self._write('.secret_key', 'k')
        git(self.work, 'add', '-f', '.secret_key')
        git(self.work, 'commit', '-q', '-m', 'oops')
        lock = os.path.join(self.work, '.git', 'index.lock')
        open(lock, 'w').close()
        os.utime(lock, (time.time() - 3600, time.time() - 3600))
        st = self.c.get('/api/git/status?repo=project').get_json()
        ids = [p['id'] for p in st['problems']]
        for pid in ('url_credentials', 'tracked_secret', 'index_lock'):
            self.assertIn(pid, ids)
        self.assertNotIn('secret123', str(st))                                   # scrubbed from the remotes list
        for fix in ('remove_lock', 'strip_url', 'untrack_secret'):
            with self.subTest(fix=fix):
                self.assertEqual(self.post('fix', id=fix).status_code, 200)
        self.assertEqual(git(self.work, 'remote', 'get-url', 'origin').strip(), 'https://example.com/r.git')
        self.assertFalse(os.path.exists(lock))
        self.assertNotIn('.secret_key', git(self.work, 'ls-files', '--cached', '.secret_key'))

    def test_identity(self):
        r = self.post('identity', name='New Name', email='new@example.com', scope='local')
        self.assertEqual(r.get_json()['overview']['identity']['local_email'], 'new@example.com')
        self.assertEqual(self.post('identity', name='x', email='bad').status_code, 400)
        self.assertEqual(self.post('identity', name='x', email='a@b.c', scope='system').status_code, 400)

    # ── token safety ────────────────────────────────────────

    def test_token_is_write_only_and_never_leaks(self):
        r = self.c.post('/api/git/credentials', json={'username': 'bot', 'token': TOKEN})
        self.assertNotIn(TOKEN, r.get_data(as_text=True))
        self.assertEqual(r.get_json()['token_hint'], '…' + TOKEN[-4:])
        self.assertEqual(stat.S_IMODE(os.stat(credentials.PATH).st_mode), 0o600)
        for url in ['/api/git/credentials', '/api/git/status?repo=project', '/api/git/summary?repo=project']:
            self.assertNotIn(TOKEN, self.c.get(url).get_data(as_text=True))
        self._write('x.txt', 'x\n')
        r = self.post('commit', message='with token around', push=True)
        self.assertEqual(r.status_code, 200, r.get_json())
        for root, _, files in os.walk(os.path.join(self.work, '.git')):
            for name in files:
                with open(os.path.join(root, name), 'rb') as f:
                    self.assertNotIn(TOKEN.encode(), f.read(), os.path.join(root, name))
        with open(os.path.join(config.BASE_DIR, 'config.json'), encoding='utf-8') as f:
            self.assertNotIn(TOKEN, f.read())
        self.assertEqual(git_ops.scrub(f'fatal: {TOKEN} https://a:b@h/x'), 'fatal: *** https://***@h/x')
        # an empty token field keeps the token; clear_token removes it
        self.c.post('/api/git/credentials', json={'username': 'bot2', 'token': ''})
        self.assertEqual(credentials.git()['token'], TOKEN)
        self.c.post('/api/git/credentials', json={'clear_token': True})
        self.assertEqual(credentials.git()['token'], '')

    def test_token_in_tracked_file_is_reported(self):
        credentials.set_git('bot', TOKEN)
        self._write('leak.txt', f'token={TOKEN}\n')
        git(self.work, 'add', 'leak.txt')
        probs = {p['id']: p for p in self.c.get('/api/git/status?repo=project').get_json()['problems']}
        self.assertIn('token_in_repo', probs)
        self.assertIn('leak.txt', probs['token_in_repo']['title'])
        self.assertNotIn(TOKEN, str(probs))

    def test_credentials_file_is_outside_the_repository(self):
        real = os.path.join(os.path.expanduser('~'), '.config', 'systemmngmntservice', 'credentials.json')
        self.assertFalse(os.path.realpath(real).startswith(os.path.realpath(config.BASE_DIR) + os.sep))


class NotARepo(unittest.TestCase):
    def test_folder_without_git(self):
        saved = config.CFG['target_dir']
        config.CFG['target_dir'] = tempfile.mkdtemp(dir=TMP)
        try:
            c = client(logged_in=True)
            self.assertEqual(c.get('/api/git/status?repo=project').status_code, 409)
            self.assertIn('error', c.get('/api/git/summary?repo=project').get_json())
        finally:
            config.CFG['target_dir'] = saved


if __name__ == '__main__':
    unittest.main()


class ClonedProjects(unittest.TestCase):
    """target_dir that is not a repository itself but contains projects cloned from a remote."""

    def setUp(self):
        self.base = tempfile.mkdtemp(dir=TMP)
        self.origin = os.path.join(self.base, 'gh.git')
        git(self.base, 'init', '-q', '--bare', '-b', 'main', self.origin)
        seed = os.path.join(self.base, 'seed')
        git(self.base, 'clone', '-q', self.origin, seed)
        with open(os.path.join(seed, 'main.py'), 'w') as f:
            f.write('print(1)\n')
        git(seed, 'add', '.')
        git(seed, 'commit', '-q', '-m', 'init')
        git(seed, 'push', '-q', 'origin', 'main')
        self.target = os.path.join(self.base, 'target')
        os.makedirs(os.path.join(self.target, 'group', 'plain'))
        git(self.base, 'clone', '-q', self.origin, os.path.join(self.target, 'app'))
        git(self.base, 'clone', '-q', self.origin, os.path.join(self.target, 'group', 'lib'))
        git(os.path.join(self.target, 'app'), 'remote', 'set-url', 'origin', 'git@github.com:owner/app.git')
        self._saved = config.CFG['target_dir']
        config.CFG['target_dir'] = self.target
        self.c = client(logged_in=True)

    def tearDown(self):
        config.CFG['target_dir'] = self._saved

    def test_scan_and_tree_status(self):
        ids = [r['id'] for r in self.c.get('/api/git/repos').get_json()['repos']]
        self.assertIn('dir:app', ids)
        self.assertIn('dir:group/lib', ids)
        with open(os.path.join(self.target, 'app', 'main.py'), 'w') as f:
            f.write('print(2)\n')
        d = self.c.get('/api/git/tree_status').get_json()
        self.assertEqual(d['files'], {os.path.join(self.target, 'app', 'main.py'): 'modified'})
        app = next(r for r in d['repos'] if r['id'] == 'dir:app')
        self.assertEqual((app['branch'], app['changes'], app['remote']['slug']), ('main', 1, 'owner/app'))
        self.assertEqual(app['remote']['web'], 'https://github.com/owner/app')
        st = self.c.get('/api/git/status?repo=dir:app').get_json()
        self.assertEqual(st['repo']['remote']['host'], 'github.com')
        r = self.c.post('/api/git/commit', json={'repo': 'dir:app', 'message': 'edit from the panel', 'paths': ['main.py']})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.c.get('/api/git/tree_status').get_json()['files'], {})

    def test_repo_ids_are_confined_to_target_dir(self):
        for bad in ['dir:../gh.git', 'dir:group/plain', 'dir:', 'dir:/etc', 'dir:group/../../seed']:
            with self.subTest(bad=bad):
                self.assertEqual(self.c.get('/api/git/status?repo=' + bad).status_code, 404)

    def test_clone_and_init(self):
        url = 'file://' + self.origin
        r = self.c.post('/api/git/clone', json={'url': url, 'name': 'copy'})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()['repo'], 'dir:copy')
        self.assertTrue(os.path.isfile(os.path.join(self.target, 'copy', 'main.py')))
        self.assertEqual(self.c.post('/api/git/clone', json={'url': url, 'name': 'copy'}).status_code, 409)
        for bad in ['--upload-pack=x', 'ftp://h/x', 'https://u:p@github.com/o/r.git']:
            with self.subTest(url=bad):
                self.assertEqual(self.c.post('/api/git/clone', json={'url': bad, 'name': 'x'}).status_code, 400)
        self.assertEqual(self.c.post('/api/git/clone', json={'url': url, 'name': '../out'}).status_code, 400)
        self.assertEqual(self.c.post('/api/git/init', json={}).status_code, 200)
        self.assertEqual(self.c.post('/api/git/init', json={}).status_code, 409)

    def test_remote_info(self):
        self.assertEqual(git_ops.remote_info('https://tok@github.com/o/r.git')['web'], 'https://github.com/o/r')
        self.assertEqual(git_ops.remote_info('ssh://git@gitlab.lan:2222/g/p.git')['slug'], 'g/p')
        self.assertEqual(git_ops.remote_info('/srv/repo.git')['web'], '')
