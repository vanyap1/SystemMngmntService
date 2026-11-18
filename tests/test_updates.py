"""Panel self-update (core/updates.py, /api/update/*) on throw-away repositories: the panel's 'panel' repository
is pointed to a temporary clone, so the real repository and its upstream are never fetched or changed."""
import os
import tempfile
import time
import unittest
from unittest import mock

from tests.support import TMP, client, config  # noqa: F401  (support first)
from core import git_ops, updates
from core.git_ops import GitError
from tests.test_git import git


class SelfUpdate(unittest.TestCase):
    def setUp(self):
        base = tempfile.mkdtemp(dir=TMP)
        self.origin = os.path.join(base, 'origin.git')
        self.panel = os.path.join(base, 'panel')
        dev = os.path.join(base, 'dev')
        git(base, 'init', '-q', '--bare', '-b', 'main', self.origin)
        git(base, 'clone', '-q', self.origin, dev)
        self._commit(dev, 'app.py', 'v1', 'first')
        git(dev, 'push', '-q', 'origin', 'main')
        git(base, 'clone', '-q', self.origin, self.panel)
        self._commit(dev, 'app.py', 'v2', 'second')
        self._commit(dev, 'new.py', 'x', 'third')
        git(dev, 'push', '-q', 'origin', 'main')
        self._saved = config.BASE_DIR
        config.BASE_DIR = self.panel              # repo_sources() reads it at call time
        updates._reset_for_tests()
        self.c = client(logged_in=True)

    def tearDown(self):
        config.BASE_DIR = self._saved
        config.CFG['update_check_minutes'] = 0
        updates._reset_for_tests()

    @staticmethod
    def _commit(repo, name, text, msg):
        with open(os.path.join(repo, name), 'w') as f:
            f.write(text)
        git(repo, 'add', '.')
        git(repo, 'commit', '-q', '-m', msg)

    def _wait(self):
        for _ in range(100):
            st = updates.status()
            if not st['checking']:
                return st
            time.sleep(0.05)
        self.fail('check did not finish')

    def test_disabled_does_not_check(self):
        st = updates.status()
        self.assertFalse(st['checking'])
        self.assertFalse(st['enabled'])
        self.assertEqual(st['checked'], 0)

    def test_check_reports_new_commits(self):
        updates.status(force=True)
        st = self._wait()
        self.assertTrue(st['online'])
        self.assertTrue(st['available'])
        self.assertEqual(st['behind'], 2)
        self.assertEqual([c['subject'] for c in st['commits']], ['third', 'second'])
        self.assertEqual(st['upstream'], 'origin/main')

    def test_due_by_interval(self):
        config.CFG['update_check_minutes'] = 60
        self.assertTrue(updates.status()['checking'])         # never checked → due
        self._wait()
        self.assertFalse(updates.status()['checking'])        # just checked → not due

    def test_apply_fast_forwards(self):
        updates.status(force=True)
        self._wait()
        with open(os.path.join(self.panel, 'local.txt'), 'w') as f:   # untracked file survives
            f.write('keep')
        r = self.c.post('/api/update/apply')
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.assertTrue(d['restart'])
        self.assertEqual(d['status']['behind'], 0)
        self.assertTrue(os.path.exists(os.path.join(self.panel, 'new.py')))
        self.assertTrue(os.path.exists(os.path.join(self.panel, 'local.txt')))
        self.assertFalse(self.c.post('/api/update/apply').get_json()['restart'])   # nothing new

    def test_offline_upstream(self):
        git(self.panel, 'remote', 'set-url', 'origin', os.path.join(TMP, 'missing.git'))
        updates.status(force=True)
        st = self._wait()
        self.assertFalse(st['online'])
        self.assertFalse(st['available'])
        self.assertTrue(st['error'])

    def test_restart_needs_systemd(self):
        saved = updates.own_unit
        updates.own_unit = lambda: None
        try:
            with self.assertRaises(GitError):
                updates.restart()
            self.assertEqual(self.c.post('/api/update/restart').status_code, 409)
        finally:
            updates.own_unit = saved

    def _read(self, name):
        with open(os.path.join(self.panel, name)) as f:
            return f.read()

    def test_force_update_clean_fast_forward(self):
        p = self.c.post('/api/update/plan').get_json()
        self.assertEqual((p['behind'], p['issues']), (2, []))
        with mock.patch.object(updates, 'own_unit', return_value=None):
            r = self.c.post('/api/update/force', json={}).get_json()
        self.assertTrue(r['changed'])
        self.assertIsNone(r['restart'])                                        # not a service here
        self.assertEqual(self._read('app.py'), 'v2')

    def test_force_update_saves_local_changes_and_keeps_config(self):
        self._commit(self.panel, 'config.json', '{"default": {}}', 'config')   # tracked like the real one
        self._commit(self.panel, 'local.py', 'mine', 'a local commit')        # diverged: ahead 2, behind 2
        with open(os.path.join(self.panel, 'app.py'), 'w') as f:
            f.write('edited here')
        with open(os.path.join(self.panel, 'config.json'), 'w') as f:
            f.write('{"hosts": {"h5": {"x": 1}}}')
        with open(os.path.join(self.panel, 'new.py'), 'w') as f:              # untracked, comes with the update
            f.write('my own new.py')
        d = self.c.post('/api/update/force', json={})
        self.assertEqual(d.status_code, 409)                                  # asks first
        p = d.get_json()['plan']
        self.assertEqual(p['changed'], ['app.py'])
        self.assertEqual(p['in_way'], ['new.py'])
        self.assertEqual(p['kept'], ['config.json'])
        self.assertEqual(len(p['issues']), 3)
        self.assertEqual(self._read('app.py'), 'edited here')                 # nothing touched yet
        with mock.patch.object(updates, 'restart', return_value='systemmngmntservice.service') as rs, \
                mock.patch.object(updates, 'own_unit', return_value='systemmngmntservice.service'):
            r = self.c.post('/api/update/force', json={'confirm': True}).get_json()
        rs.assert_called_once()
        self.assertEqual(r['restart'], 'systemmngmntservice.service')
        self.assertEqual((self._read('app.py'), self._read('new.py')), ('v2', 'x'))
        self.assertEqual(self._read('config.json'), '{"hosts": {"h5": {"x": 1}}}')     # host settings kept
        self.assertFalse(os.path.exists(os.path.join(self.panel, 'local.py')))
        self.assertIn('backup/', git(self.panel, 'branch', '--list', 'backup/*'))
        self.assertIn('a local commit', git(self.panel, 'log', '--oneline', '-1', git(self.panel, 'branch', '--list', 'backup/*').strip()))
        self.assertIn('edited here', git(self.panel, 'stash', 'show', '-p', 'stash@{0}'))
        bk = os.path.join(self.panel, '.git', 'panel-update-backup')
        stamp = os.listdir(bk)[0]
        with open(os.path.join(bk, stamp, 'new.py')) as f:
            self.assertEqual(f.read(), 'my own new.py')
        with open(os.path.join(bk, stamp, 'config.json')) as f:
            self.assertIn('h5', f.read())

    def _job(self):
        for _ in range(200):
            j = self.c.get('/api/update/job').get_json()
            if not j['running']:
                return j
            time.sleep(0.05)
        self.fail('update job did not finish')

    def test_job_reports_steps_and_never_restarts(self):
        with mock.patch.object(updates, 'restart') as rs, \
                mock.patch.object(updates, 'own_unit', return_value='systemmngmntservice.service'):
            self.assertTrue(self.c.post('/api/update/job', json={}).get_json()['running'])
            j = self._job()
        rs.assert_not_called()                                                # the user restarts from the UI
        self.assertEqual(j['error'], '')
        texts = [s['text'] for s in j['steps']]
        self.assertTrue(texts[0].startswith('Fetching'))
        self.assertTrue(any(t.startswith('Resetting main') for t in texts))
        self.assertIn('Checking the new code (Python syntax)', texts)
        self.assertEqual({s['state'] for s in j['steps']}, {'ok'})
        r = j['result']
        self.assertTrue(r['changed'])
        self.assertTrue(r['can_restart'])
        self.assertEqual(r['syntax_errors'], [])
        self.assertEqual(self._read('app.py'), 'v2')

    def test_job_blocked_by_local_changes_until_confirmed(self):
        with open(os.path.join(self.panel, 'app.py'), 'w') as f:
            f.write('edited here')
        self.c.post('/api/update/job', json={})
        j = self._job()
        self.assertIn('Local changes are in the way', j['error'])
        self.assertEqual(j['plan']['changed'], ['app.py'])
        self.assertEqual(j['steps'][-1]['state'], 'err')
        self.assertEqual(self._read('app.py'), 'edited here')
        self.c.post('/api/update/job', json={'confirm': True})
        j = self._job()
        self.assertEqual((j['error'], self._read('app.py')), ('', 'v2'))
        self.assertTrue(any(s['text'].startswith('Stashing') for s in j['steps']))

    def test_job_finds_syntax_errors(self):
        os.makedirs(os.path.join(self.panel, 'core'))
        with open(os.path.join(self.panel, 'core', 'bad.py'), 'w') as f:
            f.write('def x(:\n')
        self.assertEqual(updates.syntax_errors(self.panel)[0].split(':')[0], os.path.join('core', 'bad.py'))
        with open(os.path.join(self.panel, 'core', 'bad.py'), 'w') as f:
            f.write('x = 1\n')
        self.assertEqual(updates.syntax_errors(self.panel), [])

    def test_job_needs_login(self):
        self.assertEqual(client().get('/api/update/job').status_code, 401)
        self.assertEqual(client().post('/api/update/job', json={}).status_code, 401)

    def test_status_endpoint(self):
        d = self.c.get('/api/update/status').get_json()
        self.assertIn('available', d)
        self.assertIn('boot', d)
        self.assertEqual(client().get('/api/update/status').status_code, 401)


if __name__ == '__main__':
    unittest.main()
