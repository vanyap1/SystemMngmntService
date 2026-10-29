"""core.test_runner: answer validation and real runs of the demo scripts (logs go to a temp dir)."""
import time
import unittest

from tests.support import config
from core import test_runner
from core.test_runner import TestRunner


def wait(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


class ValidateAnswer(unittest.TestCase):
    v = staticmethod(TestRunner._validate_answer)

    def test_number(self):
        p = {'type': 'number', 'min': 0, 'max': 10}
        self.assertEqual(self.v(p, '2.5'), 2.5)
        for bad in ['abc', 11, -1, None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.v(p, bad)

    def test_choice_and_buttons(self):
        for kind in ('choice', 'buttons'):
            p = {'type': kind, 'options': ['A', 'B']}
            self.assertEqual(self.v(p, 'B'), 'B')
            with self.assertRaises(ValueError):
                self.v(p, 'C')

    def test_text(self):
        p = {'type': 'text'}
        self.assertEqual(self.v(p, '  x  '), 'x')
        self.assertEqual(len(self.v(p, 'y' * 5000)), test_runner.MAX_TEXT_ANSWER)
        with self.assertRaises(ValueError):
            self.v(p, '   ')


class Runs(unittest.TestCase):
    r = test_runner.runner

    def tearDown(self):
        if self.r.is_running():
            self.r.stop()
            wait(lambda: not self.r.is_running())

    def test_scripts_listed(self):
        names = [s['name'] for s in test_runner.list_scripts()]
        self.assertIn('demo_pass_test.py', names)

    def test_bad_script_name(self):
        for name in ['../app.py', 'app.py', 'missing_test.py']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.r.start(name)

    def test_pass_run_writes_log(self):
        self.r.start('demo_pass_test.py', serial='SN-1')
        self.assertTrue(wait(lambda: not self.r.is_running()))
        self.assertEqual(self.r.run.state, 'PASS')
        self.assertIn('__SN-1_PASS.log', self.r.run.log_name)
        self.assertTrue(self.r.run.log_name.startswith(config.test_logs_dir()) or
                        any(l['name'] == self.r.run.log_name for l in test_runner.list_logs()))

    def test_operator_prompts(self):
        self.r.start('demo_operator_test.py')
        answers = [('', False), ('VTP-123456', True), ('VTP3', False), ('VTP1 220V', True), ('Continue', True),
                   ('abc', False), ('12.1', True), ('Green', True), ('No', True)]
        for value, ok in answers:
            self.assertTrue(wait(lambda: self.r.run.prompt or not self.r.is_running()))
            p = self.r.run.prompt
            self.assertIsNotNone(p, f'no prompt for {value!r}')
            if ok:
                self.r.answer(self.r.run.id, p['id'], value)
                wait(lambda: self.r.run.prompt is None or self.r.run.prompt['id'] != p['id'])
            else:
                with self.assertRaises(ValueError):
                    self.r.answer(self.r.run.id, p['id'], value)
        self.assertTrue(wait(lambda: not self.r.is_running()))
        self.assertIn(self.r.run.state, ('PASS', 'FAIL'))

    def test_stop_while_waiting_for_operator(self):
        self.r.start('demo_operator_test.py')
        self.assertTrue(wait(lambda: self.r.run.prompt))
        self.r.stop()
        self.assertTrue(wait(lambda: not self.r.is_running()))
        self.assertEqual(self.r.run.state, 'STOPPED')
        with self.assertRaises(RuntimeError):
            self.r.answer(self.r.run.id, 1, 'x')


if __name__ == '__main__':
    unittest.main()
