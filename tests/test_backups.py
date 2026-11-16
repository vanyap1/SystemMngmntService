"""Backups: core/backups.py (patterns, create / deploy job, safety checks) and routes/backups.py.

Everything happens in a temporary folder (project + backup dir); the target service is "none" or a mocked
systemctl — no real service is ever stopped.
"""
import io
import os
import tarfile
import tempfile
import shutil
import time
import unittest
from unittest import mock

from tests.support import client, config
from core import backups


def write(path, text='x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def read(path):
    with open(path) as f:
        return f.read()


def wait(timeout=20):
    end = time.time() + timeout
    while backups.running() and time.time() < end:
        time.sleep(0.05)
    return backups.job_status()


class Patterns(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(backups.parse_patterns('# c\n\n .git/ \n*.log'), ['.git/', '*.log'])
        for bad in ('../x', 'a/../b', '/', 'a\0b'):
            with self.assertRaises(backups.BackupError):
                backups.parse_patterns([bad])

    def test_matcher(self):
        m = backups.Matcher(['.git/', 'logs/*', '/notes.txt', '*.log', 'flash.bin', 'data/cache/'])
        self.assertEqual(m.match('.git', True), '.git/')
        self.assertEqual(m.match('sub/.git', True), '.git/')
        self.assertIsNone(m.match('.git', False))                    # dir-only pattern
        self.assertIsNone(m.match('logs', True))                     # the folder itself stays
        self.assertEqual(m.match('logs/a.txt', False), 'logs/*')
        self.assertEqual(m.match('logs/sub', True), 'logs/*')
        self.assertIsNone(m.match('x/logs/a.txt', False))            # anchored
        self.assertEqual(m.match('notes.txt', False), '/notes.txt')
        self.assertIsNone(m.match('sub/notes.txt', False))
        self.assertEqual(m.match('a/b/c.log', False), '*.log')
        self.assertEqual(m.match('a/flash.bin', False), 'flash.bin')
        self.assertEqual(m.match('data/cache', True), 'data/cache/')
        self.assertIsNone(m.match('x/data/cache', True))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='smms-bk-')
        self.proj = os.path.join(self.tmp, 'work', 'proj')
        self.bdir = os.path.join(self.tmp, 'bk')
        os.makedirs(self.bdir)
        write(os.path.join(self.proj, 'main.py'), 'print(1)')
        write(os.path.join(self.proj, 'config.json'), '{"local": true}')
        write(os.path.join(self.proj, 'notes.txt'))
        write(os.path.join(self.proj, 'sub', 'notes.txt'))
        write(os.path.join(self.proj, 'logs', 'a.log'))
        write(os.path.join(self.proj, 'logs', 'deep', 'b.txt'))
        write(os.path.join(self.proj, '.git', 'HEAD'))
        write(os.path.join(self.proj, 'data', 'cal.db'), 'cal')
        write(os.path.join(self.proj, 'pkg', '__pycache__', 'm.pyc'))
        os.symlink('main.py', os.path.join(self.proj, 'link.py'))
        self.saved = {k: config.CFG.get(k) for k in ('target_dir', 'backup_dir', 'service_name', 'backup_skip',
                                                     'deploy_keep', 'backup_stop_service')}
        config.CFG.update(target_dir=self.proj, backup_dir=self.bdir, service_name='none',
                          backup_skip=['.git/', '__pycache__/', 'logs/*', '/notes.txt'], deploy_keep=[],
                          backup_stop_service=True)

    def tearDown(self):
        wait()
        config.CFG.update(self.saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def names(self, archive):
        with tarfile.open(os.path.join(self.bdir, archive)) as t:
            return sorted(t.getnames())

    def make_archive(self, name, files, top=None):
        path = os.path.join(self.bdir, name)
        with tarfile.open(path, 'w:gz') as t:
            for rel, text in files.items():
                data = text.encode()
                ti = tarfile.TarInfo((top + '/' if top else '') + rel)
                ti.size = len(data)
                t.addfile(ti, io.BytesIO(data))
        return path


class Create(Base):
    def test_create_applies_patterns(self):
        backups.start_create()
        st = wait()
        self.assertEqual(st['state'], 'done', st)
        names = self.names(st['result']['archive'])
        self.assertIn('proj/main.py', names)
        self.assertIn('proj/sub/notes.txt', names)
        self.assertIn('proj/logs', names)                         # folder kept, contents skipped
        self.assertIn('proj/link.py', names)
        for gone in ('proj/notes.txt', 'proj/logs/a.log', 'proj/logs/deep', 'proj/.git', 'proj/pkg/__pycache__'):
            self.assertNotIn(gone, names)
        self.assertFalse([f for f in os.listdir(self.bdir) if f.endswith(backups.PARTIAL)])

    def test_backup_dir_inside_project_is_skipped(self):
        inner = os.path.join(self.proj, 'backups')
        os.makedirs(inner)
        config.CFG['backup_dir'] = inner
        backups.start_create()
        st = wait()
        self.assertEqual(st['state'], 'done', st)
        with tarfile.open(os.path.join(inner, st['result']['archive'])) as t:
            self.assertFalse([n for n in t.getnames() if n.startswith('proj/backups')])

    def test_partial_hidden_busy_refused_and_cancel(self):
        write(os.path.join(self.proj, 'big.bin'), 'z' * 3_000_000)
        orig = backups._Counting.read

        def slow(self, n=-1):
            time.sleep(0.02)
            return orig(self, n)
        gate = mock.patch.object(backups._Counting, 'read', slow)
        with gate:
            st = backups.start_create()
            name = next(iter(backups.busy_files()))
            time.sleep(0.2)
            c = client(logged_in=True)
            listed = c.get('/api/backups').get_json()
            self.assertNotIn(name + backups.PARTIAL, [a['name'] for a in listed['archives']])
            self.assertEqual(listed['job']['state'], 'running')
            self.assertEqual(c.post('/api/backups/create', json={}).status_code, 409)
            self.assertEqual(c.post('/api/backups/deploy', json={'filename': name}).status_code, 409)
            self.assertEqual(c.post('/api/backups/delete', json={'filename': name}).status_code, 409)
            self.assertEqual(c.post('/api/backups/delete', json={'filename': name + backups.PARTIAL}).status_code, 400)
            self.assertEqual(c.get('/backups/download/' + name + backups.PARTIAL).status_code, 302)
            self.assertEqual(c.post('/api/backups/cancel', json={}).status_code, 200)
            st = wait()
        self.assertEqual(st['state'], 'cancelled', st)
        self.assertEqual(os.listdir(self.bdir), [])

    def test_service_paused_only_when_running(self):
        config.CFG['service_name'] = 'demo.service'
        calls = []

        def fake(cmd, timeout=None):
            calls.append(cmd)
            return 'active' if 'is-active' in cmd else ''
        with mock.patch.object(backups, 'run_command', side_effect=fake):
            backups.start_create()
            self.assertEqual(wait()['state'], 'done')
        self.assertEqual([c.split()[-2] for c in calls], ['is-active', 'stop', 'start'])
        calls.clear()
        with mock.patch.object(backups, 'run_command', side_effect=lambda c, timeout=None: calls.append(c) or 'inactive'):
            backups.start_create()
            self.assertEqual(wait()['state'], 'done')
        self.assertEqual(len(calls), 1)                            # not running -> not stopped / started


class Deploy(Base):
    def test_replaces_folder_keeps_patterns_and_backs_up(self):
        config.CFG['deploy_keep'] = ['/config.json', 'data/', 'missing.ini']
        self.make_archive('new.tar.gz', {'main.py': 'print(2)', 'config.json': '{"local": false}', 'lib/x.py': ''},
                          top='proj')
        backups.start_deploy('new.tar.gz', backup_first=True)
        st = wait()
        self.assertEqual(st['state'], 'done', st)
        self.assertEqual(read(os.path.join(self.proj, 'main.py')), 'print(2)')
        self.assertEqual(read(os.path.join(self.proj, 'config.json')), '{"local": true}')   # kept
        self.assertEqual(read(os.path.join(self.proj, 'data', 'cal.db')), 'cal')            # kept folder
        self.assertTrue(os.path.isfile(os.path.join(self.proj, 'lib', 'x.py')))
        self.assertFalse(os.path.exists(os.path.join(self.proj, 'notes.txt')))                    # old file gone
        self.assertFalse(os.path.exists(os.path.join(self.proj, '.git')))
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.proj))), ['proj'])               # no leftovers
        full = self.names(st['result']['auto_backup'])
        self.assertIn('proj/main.py', full)
        self.assertIn('proj/.git/HEAD', full)                    # the safety backup ignores the skip patterns
        self.assertIn('proj/notes.txt', full)
        self.assertTrue(any('matched nothing: missing.ini' in l for l in st['log']))

    def test_flat_archive_and_no_backup(self):
        self.make_archive('flat.tar.gz', {'app': 'bin', 'app.yml': 'cfg'})
        backups.start_deploy('flat.tar.gz', backup_first=False)
        st = wait()
        self.assertEqual(st['state'], 'done', st)
        self.assertEqual(sorted(os.listdir(self.proj)), ['app', 'app.yml'])
        self.assertEqual(os.listdir(self.bdir), ['flat.tar.gz'])

    def test_bad_archive_leaves_project_untouched(self):
        with open(os.path.join(self.bdir, 'broken.tar.gz'), 'wb') as f:
            f.write(b'not a tar')
        backups.start_deploy('broken.tar.gz', backup_first=False)
        self.assertEqual(wait()['state'], 'error')
        self.assertTrue(os.path.isfile(os.path.join(self.proj, 'main.py')))
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.proj))), ['proj'])

    def test_unsafe_members_refused(self):
        for name, files in (('abs.tar.gz', {'/etc/x': ''}), ('dots.tar.gz', {'../x': ''})):
            self.make_archive(name, files)
            backups.start_deploy(name, backup_first=False)
            st = wait()
            self.assertEqual(st['state'], 'error', name)
            self.assertIn('Unsafe', st['error'])
        path = os.path.join(self.bdir, 'link.tar.gz')
        with tarfile.open(path, 'w:gz') as t:
            ti = tarfile.TarInfo('evil')
            ti.type, ti.linkname = tarfile.SYMTYPE, self.tmp
            t.addfile(ti)
            ti = tarfile.TarInfo('evil/pwned')
            t.addfile(ti, io.BytesIO(b''))
        backups.start_deploy('link.tar.gz', backup_first=False)
        self.assertIn('symlink', wait()['error'])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'pwned')))
        self.assertTrue(os.path.isfile(os.path.join(self.proj, 'main.py')))

    def test_target_checks(self):
        self.assertEqual(backups.check_deploy_target(self.proj), '')
        self.assertIn('system or home', backups.check_deploy_target('/home'))
        self.assertIn('system or home', backups.check_deploy_target(os.path.expanduser('~')))
        self.assertIn('panel', backups.check_deploy_target(config.BASE_DIR))
        config.CFG['backup_dir'] = os.path.join(self.proj, 'bk')
        self.assertIn('backup directory', backups.check_deploy_target(self.proj))
        config.CFG['target_dir'] = os.path.expanduser('~')
        self.make_archive('x.tar.gz', {'a': ''})
        with self.assertRaises(backups.BackupError):
            backups.start_deploy('x.tar.gz')


class Routes(Base):
    def test_preview_and_settings_validation(self):
        c = client(logged_in=True)
        r = c.post('/api/backups/preview', json={'skip': ['.git/', 'logs/*'], 'keep': ['/config.json', 'nope']}).get_json()
        paths = [s['path'] for s in r['skipped']]
        self.assertIn('.git/', paths)
        self.assertIn('logs/a.log', paths)
        self.assertEqual([k['path'] for k in r['kept']], ['config.json'])
        self.assertEqual(r['unused_keep'], ['nope'])
        self.assertEqual(c.post('/api/backups/preview', json={'skip': ['../x']}).status_code, 400)
        self.assertEqual(c.post('/api/settings', json={'backup_skip': ['a/../b']}).status_code, 400)

    def test_tree(self):
        c = client(logged_in=True)
        r = c.post('/api/backups/tree', json={'path': '', 'skip': ['.git/', '*.log', '/notes.txt'], 'keep': ['/config.json']}).get_json()
        items = {i['rel']: i for i in r['items']}
        self.assertEqual(items['.git']['skip'], '.git/')
        self.assertEqual(items['notes.txt']['skip'], '/notes.txt')
        self.assertEqual(items['config.json']['keep'], '/config.json')
        self.assertTrue(items['logs']['dir'])
        self.assertEqual(list(items)[0], '.git')                                 # folders first
        sub = c.post('/api/backups/tree', json={'path': 'logs', 'skip': ['*.log']}).get_json()
        self.assertEqual({i['rel']: i['skip'] for i in sub['items']}, {'logs/deep': None, 'logs/a.log': '*.log'})
        for bad in ('../', 'x/../..', 'missing', 'link.py'):
            with self.subTest(path=bad):
                self.assertIn(c.post('/api/backups/tree', json={'path': bad}).status_code, (400, 404))

    def test_archive_names(self):
        self.assertIsNone(backups.archive_path('../x.tar.gz'))
        self.assertIsNone(backups.archive_path('x.tar.gz' + backups.PARTIAL))
        self.assertIsNone(backups.archive_path('.hidden.tar.gz'))
        self.assertTrue(backups.archive_path('x.tar.gz').endswith('/bk/x.tar.gz'))


if __name__ == '__main__':
    unittest.main()
