"""core.test_runner: answer validation and real runs of the demo scripts (logs go to a temp dir)."""
import os
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

    # Only demo scripts without hardware run here: demo_pass_test.py talks to the bench PSU (relays, outputs).
    def test_pass_run_writes_log(self):
        self.r.start('demo_serial_test.py', serial='test')
        self.assertTrue(wait(lambda: not self.r.is_running()))
        self.assertEqual(self.r.run.state, 'PASS')
        self.assertIn('__test_PASS.log', self.r.run.log_name)
        self.assertTrue(self.r.run.log_name.startswith(config.test_logs_dir()) or
                        any(l['name'] == self.r.run.log_name for l in test_runner.list_logs()))

    def test_serial_reaches_the_script(self):
        """The Serial number field is passed as --sn: the script sees it (ts.serial), log name and header carry it."""
        self.r.start('demo_serial_test.py', serial='VTP-123456')
        self.assertTrue(wait(lambda: not self.r.is_running()))
        run = self.r.run
        self.assertEqual(run.state, 'PASS')
        rows = {x['name']: x for x in run.results}
        self.assertEqual(rows['Serial number provided']['condition'], 'VTP-123456')
        self.assertIn('Unit under test: VTP-123456', run.output)
        self.assertIn('__VTP-123456_PASS.log', run.log_name)
        with open(os.path.join(config.test_logs_dir(), run.log_name)) as fh:
            self.assertIn('Serial:   VTP-123456', fh.read())

    def test_step_time_is_the_duration_of_the_step(self):
        self.r.start('demo_serial_test.py', serial='test')     # steps 0.5 s apart after "Fixture power on"
        self.assertTrue(wait(lambda: not self.r.is_running()))
        steps = [x for x in self.r.run.results if x['status'] != 'SECTION']
        by = {x['name']: x for x in steps}
        self.assertAlmostEqual(by['Supply 5V']['dt'], 0.5, delta=0.25)
        self.assertGreater(by['Supply 5V']['t'], 0.4)               # t stays "since the start"
        for a, b in zip(steps, steps[1:]):
            self.assertAlmostEqual(b['dt'], b['t'] - a['t'], delta=0.02)

    def test_no_serial(self):
        self.r.start('demo_serial_test.py')
        self.assertTrue(wait(lambda: not self.r.is_running()))
        self.assertEqual(self.r.run.state, 'FAIL')
        self.assertEqual(self.r.run.results[0]['status'], 'FAIL')

    def test_emergency_stop_watch_aborts(self):
        started = time.time()
        self.r.start('demo_estop_test.py')
        self.assertTrue(wait(lambda: not self.r.is_running(), 15))
        run = self.r.run
        self.assertLess(time.time() - started, 7)                     # the 10 s burn-in was interrupted
        self.assertEqual(run.state, 'ERROR')
        names = [(x['name'], x['status']) for x in run.results]
        self.assertIn(('Emergency stop', 'ERROR'), names)
        self.assertNotIn('Burn-in', [n for n, _ in names])
        self.assertEqual(names[-1], ('Fixture power off', 'PASS'))     # finalize ran
        self.assertTrue(any(n.startswith('Aborted: Emergency stop') for n, st in names if st == 'SECTION'))

    def test_stop_button_with_a_watch(self):
        """Stop of the Tests page (SIGINT) still works while a watch owns the Ctrl+C handler."""
        self.r.start('demo_estop_test.py')                          # its watch would abort only after 2 s
        self.assertTrue(wait(lambda: len(self.r.run.results) >= 2))
        self.r.stop()
        self.assertTrue(wait(lambda: not self.r.is_running()))
        self.assertEqual(self.r.run.state, 'STOPPED')
        self.assertEqual(self.r.run.results[-1]['name'], 'Fixture power off')

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
