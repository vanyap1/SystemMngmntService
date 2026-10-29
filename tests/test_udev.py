"""core.udev: rule file names and the rules linter (read-only)."""
import unittest

from tests.support import app  # noqa: F401
from core import udev


class RuleNames(unittest.TestCase):
    def test_bad_names(self):
        for name in ['../x.rules', 'x.conf', 'a/b.rules', '', '.rules']:
            with self.subTest(name=name):
                with self.assertRaises(udev.RuleError):
                    udev._rule_path('local', name)

    def test_system_dirs_are_read_only(self):
        _, editable = udev.rules_dir('local')
        self.assertTrue(editable)
        self.assertFalse(any(e for k, _, e in udev.RULES_DIRS if k != 'local'))


class Lint(unittest.TestCase):
    def test_valid_rules(self):
        text = ('# comment\n'
                'SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", SYMLINK+="ftdi", MODE="0666"\n'
                'ACTION=="add", KERNEL=="sd*", \\\n'
                '  RUN+="/bin/true"\n')
        self.assertEqual(udev.lint_rules(text), [])

    def test_problems(self):
        cases = {
            'FOO=="x"\n': 'Unknown key',
            'ATTR=="x"\n': 'needs {attribute}',
            'ATTRS{idVendor}="0403"\n': 'only supports',
            'KERNEL=="a" MODE="0666"\n': 'Expected ","',
        }
        for text, msg in cases.items():
            with self.subTest(text=text):
                problems = udev.lint_rules(text)
                self.assertTrue(problems and msg in problems[0]['message'], problems)
                self.assertEqual(problems[0]['line'], 1)


if __name__ == '__main__':
    unittest.main()
