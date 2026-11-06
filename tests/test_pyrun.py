"""Run / debug Python scripts from the editor (core/pyrun.py, core/pydbg_agent.py, /api/pyrun/*).
Scripts are written to a temporary target_dir; every test stops its session."""
import os
import tempfile
import time
import unittest

from tests.support import TMP, client, config  # noqa: F401  (support first)
from core import pyrun

HELPER = '''def add(a, b):
    total = a + b
    return total
'''
DEMO = '''import helper

class Box:
    def __init__(self):
        self.items = {'a': 1, 'b': [1, 2, 3]}

def main():
    box = Box()
    x = helper.add(2, 3)
    name = input('name? ')
    print('hello', name, x)
    try:
        return 1 / 0
    finally:
        print('finalize ran')

main()
'''
LOOP = '''import time
try:
    for i in range(600):
        time.sleep(0.05)
finally:
    print('cleanup done')
'''


class PyRun(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        for name, text in (('helper.py', HELPER), ('demo.py', DEMO), ('loop.py', LOOP), ('notes.txt', 'x')):
            with open(os.path.join(self.root, name), 'w') as f:
                f.write(text)
        self.demo = os.path.join(self.root, 'demo.py')
        self._saved = config.CFG['target_dir']
        config.CFG['target_dir'] = self.root
        self.c = client(logged_in=True)
        self.sid = None

    def tearDown(self):
        s = pyrun.current()
        if s and s.state != 'exited':
            s.stop()
            self._wait(lambda d: d['state'] == 'exited', 10)
        config.CFG['target_dir'] = self._saved

    def post(self, url, **body):
        if self.sid is not None:
            body.setdefault('id', self.sid)
        return self.c.post('/api/pyrun/' + url, json=body)

    def start(self, path=None, **kw):
        r = self.c.post('/api/pyrun/start', json={'path': path or self.demo, **kw})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.sid = r.get_json()['id']
        return r.get_json()

    def poll(self):
        return self.c.get(f'/api/pyrun/poll?id={self.sid}&since=0').get_json()

    def _wait(self, cond, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            d = self.c.get(f'/api/pyrun/poll?since=0').get_json()
            if cond(d):
                return d
            time.sleep(0.05)
        self.fail(f'timeout, last state: {d.get("state")}')

    def paused(self, line=None):
        return self._wait(lambda d: d['state'] == 'paused' and (line is None or d['paused']['line'] == line))['paused']

    # ── plain run ──
    def test_run_with_input_in_a_pty(self):
        self.start()
        self._wait(lambda d: 'name? ' in d['output'])
        self.assertEqual(self.post('input', text='Ivan\n').status_code, 200)
        d = self._wait(lambda d: d['state'] == 'exited')
        self.assertIn('hello Ivan 5', d['output'])
        self.assertIn('finalize ran', d['output'])
        self.assertIn('ZeroDivisionError', d['output'])
        self.assertEqual(d['exit_code'], 1)
        self.assertIn('Ivan', d['output'].split('name? ')[1])         # the pty echoes typed input

    def test_survives_the_request_thread(self):
        """Flask serves each request in a short-lived thread; PDEATHSIG must not fire when it exits."""
        import threading
        t = threading.Thread(target=lambda: self.c.post('/api/pyrun/start', json={'path': os.path.join(self.root, 'loop.py')}))
        t.start()
        t.join()
        time.sleep(0.6)
        s = pyrun.current()
        self.assertEqual(s.state, 'running', s.output(0)[0])
        self.assertIsNone(s.proc.poll())

    def test_spawn_outlives_caller_thread(self):
        import threading
        from core import spawn
        box = {}
        t = threading.Thread(target=lambda: box.update(p=spawn.popen(['sleep', '5'])))
        t.start()
        t.join()
        time.sleep(0.5)
        try:
            self.assertIsNone(box['p'].poll())
        finally:
            box['p'].kill()
            box['p'].wait()

    def test_stop_runs_finally(self):
        self.start(os.path.join(self.root, 'loop.py'))
        time.sleep(0.4)
        self.post('stop')
        d = self._wait(lambda d: d['state'] == 'exited')
        self.assertIn('cleanup done', d['output'])

    # ── debugger ──
    def test_breakpoint_step_into_and_out(self):
        self.start(debug=True, breaks={self.demo: [9]})
        p = self.paused(9)
        self.assertEqual(p['func'], 'main')
        self.assertEqual([v['name'] for v in p['vars']], ['box'])
        self.post('cmd', action='step')
        p = self.paused(2)
        self.assertTrue(p['file'].endswith('helper.py'))
        self.assertEqual([f['func'] for f in p['stack']], ['<module>', 'main', 'add'])
        self.post('cmd', action='return')
        p = self.paused(10)                                  # the caller's next line, the result assigned
        self.assertTrue(p['file'].endswith('demo.py'))
        self.assertIn(('x', '5'), [(v['name'], v['value']) for v in p['vars']])

    def test_eval_hover_and_children(self):
        self.start(debug=True, breaks={self.demo: [10]})
        self.paused(10)
        r = self.post('eval', expr='x', hover=True).get_json()
        self.assertEqual((r['type'], r['value']), ('int', '5'))
        r = self.post('eval', expr="box.items['b']", hover=True).get_json()
        self.assertEqual(r['value'], '[1, 2, 3]')
        r = self.post('eval', expr='print("side effect")', hover=True).get_json()
        self.assertIn('error', r)                              # hover never calls code
        self.assertEqual(self.post('eval', expr='x * 2').get_json()['value'], '10')   # Evaluate box may
        self.assertEqual(self.post('eval', expr='nope').status_code, 400)
        kids = self.post('vars', expr='box').get_json()['vars']
        self.assertEqual([k['name'] for k in kids], ['items'])
        self.assertTrue(kids[0]['more'])
        sub = self.post('vars', expr='box.items').get_json()['vars']
        self.assertEqual([k['name'] for k in sub], ["'a'", "'b'"])
        self.assertEqual(sub[1]['expr'], "box.items['b']")
        frames = self.post('vars', frame=0).get_json()['vars']  # module frame: Box/main/helper hidden
        self.assertEqual(frames, [])

    def test_breakpoints_change_while_running_and_pause(self):
        self.start(os.path.join(self.root, 'loop.py'), debug=True)
        time.sleep(0.3)
        self.assertEqual(self.post('cmd', action='pause').status_code, 200)
        p = self.paused()
        self.assertTrue(p['file'].endswith('loop.py'))
        self.post('cmd', action='continue')
        self._wait(lambda d: d['state'] == 'running')
        loop = os.path.join(self.root, 'loop.py')
        self.assertEqual(self.c.post('/api/pyrun/breaks', json={'breaks': {loop: [4]}}).status_code, 200)
        self.assertEqual(self.paused(4)['reason'], 'breakpoint')

    def test_run_previous_line_again(self):
        with open(os.path.join(self.root, 'again.py'), 'w') as f:
            f.write('count = 0\n\n\ndef bump():\n    global count\n    count += 1\n\n\n'
                    'for i in range(2):\n    pass\n\nbump()\nx = count * 10\nprint("x =", x)\n')
        path = os.path.join(self.root, 'again.py')
        self.start(path, debug=True, breaks={path: [12]})
        self.paused(12)
        self.post('cmd', action='next')
        self.paused(13)
        r = self.post('cmd', action='jump')                        # back to the previous line
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()['line'], 12)
        self.paused(12)
        self.post('cmd', action='next')
        self.paused(13)
        self.assertEqual(self.post('eval', expr='count', hover=True).get_json()['value'], '2')   # bump() ran twice
        r = self.post('cmd', action='jump', line=10)              # into a for body: refused by Python
        self.assertEqual(r.status_code, 409)
        self.assertIn('for loop', r.get_json()['error'])
        self.assertEqual(self.post('cmd', action='jump', line='x').status_code, 400)
        self.post('cmd', action='continue')
        d = self._wait(lambda d: d['state'] == 'exited')
        self.assertIn('x = 20', d['output'])

    def test_uncaught_exception_pauses_post_mortem(self):
        self.start(debug=True)
        self._wait(lambda d: 'name? ' in d['output'])
        self.post('input', text='A\n')
        p = self.paused()
        self.assertEqual(p['reason'], 'exception')
        self.assertIn('ZeroDivisionError', p['exception'])
        self.assertEqual(p['line'], 13)
        self.post('cmd', action='continue')
        d = self._wait(lambda d: d['state'] == 'exited')
        self.assertEqual(d['exit_code'], 1)

    def test_stop_while_paused_quits_with_finally(self):
        self.start(debug=True, breaks={self.demo: [13]})
        self._wait(lambda d: 'name? ' in d['output'])
        self.post('input', text='B\n')
        self.paused(13)
        self.post('stop')
        d = self._wait(lambda d: d['state'] == 'exited')
        self.assertIn('finalize ran', d['output'])
        self.assertEqual(d['exit_code'], 130)
        self.assertNotIn('ZeroDivisionError', d['output'])

    def test_stop_on_entry(self):
        self.start(debug=True, stop_on_entry=True)
        p = self.paused(1)
        self.assertEqual(p['reason'], 'entry')

    # ── rules ──
    def test_validation_and_single_session(self):
        for path in ('/etc/passwd', os.path.join(self.root, 'notes.txt'), os.path.join(self.root, 'none.py'),
                     os.path.join(self.root, '..', 'x.py')):
            with self.subTest(path=path):
                self.assertIn(self.c.post('/api/pyrun/start', json={'path': path}).status_code, (403, 404))
        self.assertEqual(self.c.post('/api/pyrun/start', json={'path': self.demo, 'args': 'x'}).status_code, 400)
        self.start(os.path.join(self.root, 'loop.py'))
        self.assertEqual(self.c.post('/api/pyrun/start', json={'path': self.demo}).status_code, 409)
        self.assertEqual(self.c.post('/api/tests/start', json={'script': 'demo_serial_test.py'}).status_code, 409)
        self.assertEqual(self.post('cmd', action='next').status_code, 409)      # not a debug session
        self.assertEqual(self.post('cmd', action='bogus').status_code, 400)

    def test_blocked_while_a_test_runs(self):
        saved = pyrun.blocked
        pyrun.blocked = lambda: 'A test script is running'
        try:
            self.assertEqual(self.c.post('/api/pyrun/start', json={'path': self.demo}).status_code, 409)
        finally:
            pyrun.blocked = saved

    def test_arguments(self):
        with open(os.path.join(self.root, 'args.py'), 'w') as f:
            f.write('import sys, os\nprint("ARGS", sys.argv[1:], os.path.basename(os.getcwd()))\n')
        self.start(os.path.join(self.root, 'args.py'), args=['--sn', 'A 1'])
        d = self._wait(lambda d: d['state'] == 'exited')
        self.assertIn("ARGS ['--sn', 'A 1'] " + os.path.basename(self.root), d['output'])

    def test_login_required(self):
        anon = client()
        self.assertEqual(anon.get('/api/pyrun/poll').status_code, 401)
        for url in ('start', 'cmd', 'input', 'stop', 'eval', 'vars', 'breaks'):
            self.assertEqual(anon.post('/api/pyrun/' + url, json={}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
