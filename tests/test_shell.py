"""core.shell helpers."""
import os
import tempfile
import unittest

from tests.support import TMP
from core.shell import resolve_inside, run_command, sh


class ResolveInside(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(self.root, 'sub'))
        open(os.path.join(self.root, 'sub', 'f.txt'), 'w').close()

    def test_inside(self):
        p = os.path.join(self.root, 'sub', 'f.txt')
        self.assertEqual(resolve_inside(p, self.root), os.path.realpath(p))

    def test_escapes_are_rejected(self):
        for path in ['', self.root, os.path.join(self.root, '..', 'x'), '/etc/passwd', self.root + '-evil/x']:
            with self.subTest(path=path):
                self.assertIsNone(resolve_inside(path, self.root))

    def test_symlink_out_is_rejected(self):
        link = os.path.join(self.root, 'link')
        os.symlink('/etc', link)
        self.assertIsNone(resolve_inside(os.path.join(link, 'passwd'), self.root))


class Commands(unittest.TestCase):
    def test_sh_is_quiet(self):
        self.assertEqual(sh('echo hi'), 'hi')
        self.assertEqual(sh('exit 3'), '')

    def test_run_command_reports_errors(self):
        self.assertEqual(run_command('echo ok'), 'ok')
        self.assertTrue(run_command('false').startswith('Error!'))
        self.assertIn('Timed out', run_command('sleep 2', timeout=0.2))


if __name__ == '__main__':
    unittest.main()
