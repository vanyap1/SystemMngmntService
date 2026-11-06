"""Interactive terminal (core/terminal.py, /api/term/*): a real shell in a pty, streamed as Server-Sent Events."""
import json
import time
import unittest

from tests.support import client, config  # noqa: F401  (support first)
from core import terminal


def read_until(s, text, offset=0, timeout=8):
    end, out = time.time() + timeout, b''
    while time.time() < end:
        data, offset, done = s.read(offset, 0.3)
        out += data
        if text.encode() in out or done:
            break
    return out.decode('utf-8', 'replace'), offset


class Terminal(unittest.TestCase):
    def setUp(self):
        self.c = client(logged_in=True)
        self.ids = []

    def tearDown(self):
        for sid in self.ids:
            terminal.close(sid)

    def open(self, **body):
        r = self.c.post('/api/term/open', json={'cols': 100, 'rows': 30, **body})
        self.assertEqual(r.status_code, 200, r.get_json())
        d = r.get_json()
        self.ids.append(d['id'])
        return d, terminal.get(d['id'])

    def type(self, sid, text):
        self.assertEqual(self.c.post('/api/term/input', json={'id': sid, 'data': text}).status_code, 200)

    def test_shell_runs_commands_in_a_pty(self):
        d, s = self.open()
        self.type(d['id'], 'echo RESULT=$((6*7)); tty; echo $TERM\r')
        out, _ = read_until(s, 'xterm-256color')
        self.assertIn('RESULT=42', out)
        self.assertIn('/dev/pts/', out)                 # a real terminal: full-screen programs work
        self.assertIn('xterm-256color', out)

    def test_resize_reaches_the_shell(self):
        d, s = self.open()
        self.assertEqual(self.c.post('/api/term/resize', json={'id': d['id'], 'cols': 132, 'rows': 43}).status_code, 200)
        self.type(d['id'], 'stty size\r')
        out, _ = read_until(s, '43 132')
        self.assertIn('43 132', out)

    def test_ctrl_c_interrupts(self):
        d, s = self.open()
        read_until(s, '$ ')                                   # the prompt is there
        self.type(d['id'], 'sleep 30\r')
        time.sleep(0.5)
        started = time.time()
        self.type(d['id'], '\x03')
        self.type(d['id'], 'echo AFTER-$((1+1))\r')
        out, _ = read_until(s, 'AFTER-2', timeout=8)
        self.assertIn('AFTER-2', out)
        self.assertLess(time.time() - started, 5)              # sleep 30 was interrupted
        self.assertIn('^C', out)

    def test_reattach_keeps_the_session(self):
        d, s = self.open()
        d2, s2 = self.open(id=d['id'])
        self.assertTrue(d2['reattached'])
        self.assertIs(s, s2)
        d3, _ = self.open(id='nope')
        self.assertFalse(d3['reattached'])

    def test_stream_events_and_exit(self):
        d, s = self.open()
        self.type(d['id'], 'echo STREAMED\r')
        read_until(s, 'STREAMED')
        events = []
        gen = terminal.stream(s, 0)
        for chunk in gen:
            events.append(chunk)
            if 'STREAMED' in ''.join(events):
                break
        out = [json.loads(e.split('data: ', 1)[1]) for e in events if e.startswith('event: out')]
        self.assertTrue(out and out[-1]['o'] > 0)
        gen.close()
        self.type(d['id'], 'exit 3\r')
        tail = list(terminal.stream(s, out[-1]['o']))
        self.assertTrue(tail[-1].startswith('event: exit'))
        self.assertEqual(json.loads(tail[-1].split('data: ', 1)[1])['code'], 3)
        self.assertEqual(self.c.post('/api/term/input', json={'id': d['id'], 'data': 'x'}).status_code, 409)

    def test_stream_endpoint_is_sse(self):
        d, s = self.open()
        r = self.c.get(f'/api/term/stream?id={d["id"]}&from=0', buffered=False)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.mimetype == 'text/event-stream')
        first = next(r.response)
        self.assertIn(b'retry:', first if isinstance(first, bytes) else first.encode())
        r.close()

    def test_close(self):
        d, s = self.open()
        self.assertTrue(self.c.post('/api/term/close', json={'id': d['id']}).get_json()['ok'])
        end = time.time() + 5
        while not s.closed and time.time() < end:
            time.sleep(0.05)
        self.assertTrue(s.closed)
        self.assertEqual(self.c.post('/api/term/resize', json={'id': d['id'], 'cols': 80, 'rows': 20}).status_code, 404)

    def test_validation_and_login(self):
        d, _ = self.open()
        self.assertEqual(self.c.post('/api/term/input', json={'id': d['id'], 'data': 5}).status_code, 400)
        self.assertEqual(self.c.post('/api/term/input', json={'id': 'missing', 'data': 'x'}).status_code, 404)
        anon = client()
        self.assertEqual(anon.get(f'/api/term/stream?id={d["id"]}').status_code, 401)
        self.assertEqual(anon.post('/api/term/open', json={}).status_code, 401)

    def test_session_limit(self):
        saved = terminal.MAX_SESSIONS
        terminal.MAX_SESSIONS = len([s for s in terminal._sessions.values() if not s.closed]) + 1
        try:
            self.open()
            r = self.c.post('/api/term/open', json={})
            self.assertEqual(r.status_code, 429)
        finally:
            terminal.MAX_SESSIONS = saved


if __name__ == '__main__':
    unittest.main()
