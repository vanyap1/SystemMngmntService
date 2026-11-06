"""testPlatform/testWatch.py + TestStrategy.run(watch=): background checks abort a running sequence.
Every case runs in its own Python process (signal handlers belong to the main thread)."""
import os
import subprocess
import sys
import textwrap
import time
import unittest

from tests.support import ROOT

TP = os.path.join(ROOT, 'testPlatform')


def run_script(body, timeout=20):
    code = textwrap.dedent('''
        import sys, time
        sys.path.insert(0, %r)
        from testStrategy import TestStrategy, AbortTest
        from testWatch import TestWatch, EmergencyStop
        ts = TestStrategy()
        t0 = time.time()
    ''' % TP) + textwrap.dedent(body)
    env = dict(os.environ)
    env.pop('TEST_RUNNER', None)
    started = time.time()
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=timeout, env=env)
    out = r.stdout.replace('\x1b[32m', '').replace('\x1b[31m', '').replace('\x1b[33m', '').replace('\x1b[36m', '').replace('\x1b[0m', '')
    return r.returncode, out + r.stderr, time.time() - started


class Watch(unittest.TestCase):
    def test_abort_interrupts_sleep_and_runs_finalize(self):
        rc, out, took = run_script('''
            def button():
                if time.time() - t0 > 0.5:
                    raise EmergencyStop("button pressed")
            w = TestWatch().add("Emergency stop", button, interval=0.02)
            def steps():
                ts.logResult("Step 1", True)
                time.sleep(10)
                ts.logResult("Never", True)
            ok = ts.run(steps, lambda: ts.logResult("Power off", True, "OK"), watch=w)
            print("RESULT", ok, type(w.error).__name__)
        ''')
        self.assertEqual(rc, 0, out)
        self.assertLess(took, 5)
        self.assertIn('Emergency stop', out)
        self.assertIn('[ERROR]', out)
        self.assertIn('Aborted: Emergency stop', out)
        self.assertIn('Power off', out)
        self.assertNotIn('Never', out)
        self.assertIn('RESULT False WatchAbort', out)

    def test_async_check_and_require(self):
        rc, out, _ = run_script('''
            import asyncio
            state = {"n": 0}
            async def sensor():
                await asyncio.sleep(0)
                state["n"] += 1
            w = TestWatch(interval=0.02).add("Async sensor", sensor)
            w.require("Lid closed", lambda: time.time() - t0 < 0.4, "lid opened")
            def steps():
                time.sleep(5)
            ts.run(steps, None, watch=w)
            print("POLLS", state["n"] > 3)
        ''')
        self.assertIn('Lid closed', out)
        self.assertIn('lid opened', out)
        self.assertIn('POLLS True', out)

    def test_exception_text_of_other_errors(self):
        rc, out, _ = run_script('''
            def check():
                raise ConnectionError("PSU lost")
            ts.run(lambda: time.sleep(3), None, watch=TestWatch().add("PSU link", check))
        ''')
        self.assertIn('ConnectionError: PSU los', out)      # the console column is 24 chars wide

    def test_no_abort_completes_and_restores_ctrl_c(self):
        rc, out, _ = run_script('''
            import signal
            before = signal.getsignal(signal.SIGINT)
            w = TestWatch().add("Quiet", lambda: None, interval=0.01)
            ok = ts.run(lambda: time.sleep(0.3), None, watch=w)
            print("OK", ok, w.error, signal.getsignal(signal.SIGINT) is before)
            try:
                signal.raise_signal(signal.SIGINT)
            except KeyboardInterrupt:
                print("CTRL-C still works")
        ''')
        self.assertIn('OK True None True', out)
        self.assertIn('CTRL-C still works', out)

    def test_ctrl_c_during_watch_is_keyboard_interrupt(self):
        rc, out, _ = run_script('''
            import signal, threading
            w = TestWatch().add("Quiet", lambda: None)
            threading.Timer(0.3, lambda: signal.pthread_kill(threading.main_thread().ident, signal.SIGINT)).start()
            try:
                ts.run(lambda: time.sleep(5), lambda: print("FINALIZED"), watch=w)
            except KeyboardInterrupt:
                print("KEYBOARD INTERRUPT")
        ''')
        self.assertIn('FINALIZED', out)
        self.assertIn('KEYBOARD INTERRUPT', out)

    def test_finalize_is_not_interrupted(self):
        rc, out, _ = run_script('''
            def check():
                if time.time() - t0 > 0.3:
                    raise EmergencyStop("late")
            w = TestWatch(interval=0.01).add("Late", check)
            def finalize():
                time.sleep(0.6)                     # the check would fire now if it were still running
                print("FINALIZE DONE")
            ts.run(lambda: time.sleep(0.1), finalize, watch=w)
        ''')
        self.assertIn('FINALIZE DONE', out)
        self.assertNotIn('Late', out)

    def test_context_manager(self):
        rc, out, _ = run_script('''
            def check():
                raise EmergencyStop("pressed")
            try:
                with TestWatch().add("E-stop", check):
                    time.sleep(3)
            except AbortTest as e:
                print("ABORT", e.name, e.message)
        ''')
        self.assertIn('ABORT E-stop pressed', out)


if __name__ == '__main__':
    unittest.main()
