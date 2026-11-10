"""HW Utils -> Terminal: core/ttyterm.py + routes/ttyterm.py. Devices are a pseudo terminal, a local TCP echo
server and local UDP sockets — never the board's real ports."""
import base64
import os
import socket
import socketserver
import threading
import time
import unittest
from unittest import mock

from tests.support import client, config  # noqa: F401
from core import modbus, ttyterm


def wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def rx_bytes(sid, since=0):
    d = ttyterm.get(sid).read(since)
    return b''.join(base64.b64decode(c['b64']) for c in d['chunks'] if c['dir'] == 'rx'), d


class Pty(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()
        self.path = os.ttyname(self.slave)
        self.p = mock.patch.object(modbus, '_PORT', modbus.re.compile(r'^/dev/'))
        self.p.start()

    def tearDown(self):
        ttyterm.close_all()
        self.p.stop()
        for fd in (self.slave, self.master):
            try:
                os.close(fd)
            except OSError:
                pass

    def test_serial_receive_send_lines_and_exclusive(self):
        st = ttyterm.open_session({'transport': 'serial', 'port': self.path, 'baud': 115200})
        self.assertFalse(st['closed'])
        os.write(self.master, b'{"t": 21.5, "ok": true}\r\nhello')
        self.assertTrue(wait(lambda: b'hello' in rx_bytes(st['id'])[0]))
        s = ttyterm.get(st['id'])
        s.send(ttyterm.decode_payload('AT\\r\\n', False))
        self.assertEqual(os.read(self.master, 64), b'AT\r\n')
        self.assertEqual(s.state()['tx'], 4)
        d = s.read(0)
        self.assertEqual([c['dir'] for c in d['chunks']][0], 'sys')
        self.assertEqual(s.read(d['next'])['chunks'], [])
        self.assertIsNone(s.state()['lines'])                  # a pty has no modem lines (a USB adapter has)
        with self.assertRaises(ttyterm.TtyError):
            s.set_lines(dtr=False)
        # the port is held exclusively: Modbus gets "in use"
        with self.assertRaises(modbus.ModbusError) as cm:
            modbus.run({'transport': 'rtu', 'port': self.path, 'baud': 9600, 'timeout': 50}, [{'unit': 1, 'fn': 3, 'addr': 0, 'count': 1}])
        self.assertIn('in use', str(cm.exception))
        self.assertEqual(cm.exception.status, 409)
        with self.assertRaises(ttyterm.TtyError):
            ttyterm.open_session({'transport': 'serial', 'port': self.path, 'baud': 9600})
        ttyterm.close(st['id'])
        self.assertTrue(ttyterm.get(st['id']).state()['closed'])
        with self.assertRaises(ttyterm.TtyError):
            s.send(b'x')

    def test_blocked_by_test_and_lease(self):
        with mock.patch.object(modbus, 'blocked', return_value='A test script is running'):
            with self.assertRaises(ttyterm.TtyError) as cm:
                ttyterm.open_session({'transport': 'serial', 'port': self.path})
            self.assertEqual(cm.exception.status, 409)
        with mock.patch.object(ttyterm, 'LEASE_SECONDS', 0.3):
            st = ttyterm.open_session({'transport': 'serial', 'port': self.path})
            self.assertTrue(wait(lambda: ttyterm.get(st['id']).closed, 3))
            self.assertIn('nobody reads', b''.join(base64.b64decode(c['b64']) for c in ttyterm.get(st['id']).read(0)['chunks']).decode())

    def test_missing_port(self):
        with self.assertRaises(ttyterm.TtyError) as cm:
            ttyterm.open_session({'transport': 'serial', 'port': '/dev/ttyUSB97'})
        self.assertEqual(cm.exception.status, 404)


class Net(unittest.TestCase):
    def tearDown(self):
        ttyterm.close_all()

    def test_tcp_echo_and_peer_close(self):
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                data = self.request.recv(1024)
                self.request.sendall(b'echo:' + data)
        socketserver.TCPServer.allow_reuse_address = True
        srv = socketserver.TCPServer(('127.0.0.1', 0), Echo)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        st = ttyterm.open_session({'transport': 'tcp', 'host': '127.0.0.1', 'netport': srv.server_address[1]})
        self.assertTrue(st['local'].startswith('127.0.0.1:'))
        ttyterm.get(st['id']).send(b'GET / HTTP/1.1\r\n\r\n')
        self.assertTrue(wait(lambda: rx_bytes(st['id'])[0] == b'echo:GET / HTTP/1.1\r\n\r\n'))
        self.assertTrue(wait(lambda: ttyterm.get(st['id']).closed))          # the handler returned: peer closed
        self.assertEqual(ttyterm.get(st['id']).state()['error'], 'connection closed by the peer')
        srv.server_close()
        with self.assertRaises(ttyterm.TtyError):
            ttyterm.open_session({'transport': 'tcp', 'host': '127.0.0.1', 'netport': 1})

    def test_udp_send_and_listen(self):
        peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        peer.bind(('127.0.0.1', 0))
        peer.settimeout(2)
        st = ttyterm.open_session({'transport': 'udp', 'host': '127.0.0.1', 'netport': peer.getsockname()[1], 'listen': 0})
        port = int(st['local'].split(':')[1])
        ttyterm.get(st['id']).send(b'ping')
        data, addr = peer.recvfrom(100)
        self.assertEqual(data, b'ping')
        peer.sendto(b'pong', ('127.0.0.1', port))
        self.assertTrue(wait(lambda: rx_bytes(st['id'])[0] == b'pong'))
        chunks = ttyterm.get(st['id']).read(0)['chunks']
        self.assertEqual([c['src'] for c in chunks if c['dir'] == 'rx'], ['127.0.0.1:%d' % peer.getsockname()[1]])
        peer.close()

    def test_udp_listen_port_auto(self):
        self.assertEqual(ttyterm.check_conn({'transport': 'udp'}), {'transport': 'udp', 'listen': 0})
        self.assertEqual(ttyterm.check_conn({'transport': 'udp', 'listen': '5005'}), {'transport': 'udp', 'listen': 5005})
        st = ttyterm.open_session({'transport': 'udp', 'listen': ''})
        self.assertRegex(st['local'], r'^udp :\d+$')
        self.assertNotEqual(st['local'], 'udp :0')

    def test_flood_guard(self):
        with mock.patch.object(ttyterm, 'FLOOD_CHUNKS', 50):
            st = ttyterm.open_session({'transport': 'udp', 'listen': 0})
            port = int(st['local'].split(':')[1])
            tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for _ in range(400):
                tx.sendto(b'x' * 100, ('127.0.0.1', port))
            s = ttyterm.get(st['id'])
            self.assertTrue(wait(lambda: s.flood or s.dropped))
            stored = sum(1 for c in s.read(0)['chunks'] if c['dir'] == 'rx')
            self.assertLessEqual(stored, 52)
            self.assertIn('flood guard', b''.join(base64.b64decode(c['b64']) for c in s.read(0)['chunks'] if c['dir'] == 'sys').decode())
            self.assertTrue(wait(lambda: s.dropped > 0))
            tx.close()
            self.assertTrue(wait(lambda: not s.flood, 10))                     # stream stopped: back to normal
            self.assertIn('back to normal', b''.join(base64.b64decode(c['b64']) for c in s.read(0)['chunks'] if c['dir'] == 'sys').decode())

    def test_oneshot_tcp_reply_and_no_wait(self):
        class Scpi(socketserver.BaseRequestHandler):            # one connection per command, like the bench PSU
            def handle(self):
                cmd = self.request.recv(100)
                if b'?' in cmd:
                    self.request.sendall(b'12.0158\n')
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        srv = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Scpi)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        conn = {'transport': 'tcp', 'host': '127.0.0.1', 'netport': srv.server_address[1]}
        before = len(ttyterm.sessions())
        r = ttyterm.oneshot(conn, b'ADC:MEAS:EXT1:VOLT?1\r\n')
        self.assertEqual(r['end'], 'closed')
        self.assertEqual([c['dir'] for c in r['chunks']], ['sys', 'tx', 'rx', 'sys'])
        self.assertEqual(base64.b64decode(r['chunks'][2]['b64']), b'12.0158\n')
        r = ttyterm.oneshot(conn, b'OUTP ON\r\n', wait=False)
        self.assertEqual((r['end'], [c['dir'] for c in r['chunks']][:2]), ('sent', ['sys', 'tx']))   # + maybe "closed by the peer"
        self.assertEqual(len(ttyterm.sessions()), before)                  # one-shot sessions are not kept
        srv.shutdown()
        srv.server_close()

    def test_oneshot_idle_and_timeout(self):
        peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        peer.bind(('127.0.0.1', 0))

        def answer():
            data, addr = peer.recvfrom(100)
            peer.sendto(b'pong', addr)
        threading.Thread(target=answer, daemon=True).start()
        conn = {'transport': 'udp', 'host': '127.0.0.1', 'netport': peer.getsockname()[1]}
        r = ttyterm.oneshot(conn, b'ping', timeout_ms=2000)
        self.assertEqual(r['end'], 'idle')                                 # UDP never "closes": quiet after the reply
        self.assertLess(r['ms'], 1500)
        r = ttyterm.oneshot(conn, b'ping', timeout_ms=200)
        self.assertEqual(r['end'], 'timeout')
        peer.close()

    def test_sessions(self):
        c = client(logged_in=True)
        data = {'profile': {'conn': {'transport': 'tcp', 'host': '192.168.1.91', 'netport': '8080'}, 'eol': 'crlf', 'replyMs': 800,
                            'commands': [{'name': 'volt', 'data': 'ADC:MEAS:EXT1:VOLT?1', 'eol': 'crlf', 'timer': True, 'period': 500}]},
                'lines': [{'t': 1.5, 'dir': 'tx', 'text': 'ADC:MEAS:EXT1:VOLT?1'}, {'t': 2, 'dir': 'rx', 'text': '12.0158'},
                          {'dir': 'evil', 'text': 'x'}], 'note': 'PSU at :8080'}
        r = c.post('/api/tty/session/save', json={'name': 'PSU bench', 'data': data})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()['sessions'][0]['rows'], 1)
        self.assertEqual(c.post('/api/tty/session/save', json={'name': 'PSU bench', 'data': data}).status_code, 409)
        d = c.get('/api/tty/session?name=PSU bench').get_json()
        self.assertEqual((len(d['lines']), d['lines'][1]['text'], d['profile']['replyMs'], d['profile']['commands'][0]['wait']),
                         (2, '12.0158', 800, True))
        self.assertTrue(os.path.isfile(os.path.join(config.tty_sessions_dir(), 'PSU_bench.json')))
        self.assertEqual(c.post('/api/tty/session/delete', json={'name': 'PSU bench'}).get_json()['sessions'], [])
        self.assertEqual(c.post('/api/tty/oneshot', json={'conn': {'transport': 'tcp', 'host': '127.0.0.1', 'netport': 1}, 'text': 'x'}).status_code, 502)

    def test_session_limit(self):
        with mock.patch.object(ttyterm, 'MAX_SESSIONS', 1):
            ttyterm.open_session({'transport': 'udp', 'listen': 0, 'host': '127.0.0.1', 'netport': 9})
            with self.assertRaises(ttyterm.TtyError) as cm:
                ttyterm.open_session({'transport': 'udp', 'listen': 0, 'host': '127.0.0.1', 'netport': 9})
            self.assertEqual(cm.exception.status, 429)


class Misc(unittest.TestCase):
    def test_payload(self):
        self.assertEqual(ttyterm.decode_payload('A\\r\\n\\x01\\t\\\\b\\q', False), b'A\r\n\x01\t\\b\\q')
        self.assertEqual(ttyterm.decode_payload('48 65,0x6C 6c', True), b'Hell')
        self.assertEqual(ttyterm.decode_payload('ä', False), 'ä'.encode())
        with self.assertRaises(ttyterm.TtyError):
            ttyterm.decode_payload('4G', True)

    def test_profiles(self):
        d = ttyterm.check_profiles({'profiles': [{'name': 'ESP', 'eol': 'bogus', 'conn': {'transport': 'serial', 'x': 1},
                                                  'commands': [{'name': 'ver', 'data': 'AT+GMR', 'eol': 'crlf', 'period': 5, 'timer': 1}],
                                                  'view': {'hex': 1, 'evil': 2}}]})
        p = d['profiles'][0]
        self.assertEqual((p['eol'], p['commands'][0]['period'], p['commands'][0]['timer'], p['view']), ('lf', 50, True, {'hex': True}))
        self.assertNotIn('x', p['conn'])

    def test_api(self):
        self.assertEqual(client().get('/api/tty/info').status_code, 401)
        c = client(logged_in=True)
        self.assertIn('ports', c.get('/api/tty/info').get_json())
        self.assertEqual(c.get('/api/tty/read?id=nope').status_code, 404)
        r = c.post('/api/tty/open', json={'conn': {'transport': 'udp', 'listen': 0, 'host': '127.0.0.1', 'netport': 9}})
        self.assertEqual(r.status_code, 200)
        sid = r.get_json()['id']
        self.assertEqual(c.post('/api/tty/send', json={'id': sid, 'text': 'hi', 'hex': False}).status_code, 200)
        self.assertEqual(c.get(f'/api/tty/read?id={sid}&since=0').get_json()['chunks'][-1]['dir'], 'tx')
        self.assertEqual(c.post('/api/tty/close', json={'id': sid}).get_json()['closed'], True)
        r = c.post('/api/tty/profiles', json={'profiles': [{'name': 'A'}], 'current': 'A'})
        self.assertEqual(config.get('tty')['current'], 'A')


if __name__ == '__main__':
    unittest.main()
