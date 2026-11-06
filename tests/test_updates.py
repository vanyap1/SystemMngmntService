"""Panel self-update (core/updates.py, /api/update/*) on throw-away repositories: the panel's 'panel' repository
is pointed to a temporary clone, so the real repository and its upstream are never fetched or changed."""
import os
import tempfile
import time
import unittest

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

    def test_status_endpoint(self):
        d = self.c.get('/api/update/status').get_json()
        self.assertIn('available', d)
        self.assertIn('boot', d)
        self.assertEqual(client().get('/api/update/status').status_code, 401)


if __name__ == '__main__':
    unittest.main()
