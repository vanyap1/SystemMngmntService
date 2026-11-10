"""HW Utils -> Modbus: core/modbus.py (framing, transports, scan, profiles) and routes/modbus.py.

Devices are simulated: a TCP / UDP server thread (Modbus TCP or RTU frames) and a pseudo terminal for serial RTU —
never the real ports of this board.
"""
import os
import socket
import socketserver
import struct
import threading
import unittest
from unittest import mock

from tests.support import client, config  # noqa: F401
from core import modbus


class Device:
    """Register map of one simulated slave: holding registers 0..99, coils 0..31; function 4 is 'illegal'."""

    def __init__(self, unit=1):
        self.unit = unit
        self.regs = list(range(100))
        self.coils = [0] * 32

    def handle(self, unit, pdu):
        """PDU -> answer PDU, or None (not my unit = no answer)."""
        if unit not in (self.unit, 0):
            return None
        fn = pdu[0]
        if fn == 3:
            a, n = struct.unpack('>HH', pdu[1:5])
            if a + n > len(self.regs):
                return bytes([fn | 0x80, 2])
            return bytes([fn, n * 2]) + b''.join(struct.pack('>H', r) for r in self.regs[a:a + n])
        if fn == 1:
            a, n = struct.unpack('>HH', pdu[1:5])
            data = bytearray((n + 7) // 8)
            for i in range(n):
                if self.coils[a + i]:
                    data[i // 8] |= 1 << (i % 8)
            return bytes([fn, len(data)]) + bytes(data)
        if fn == 6:
            a, v = struct.unpack('>HH', pdu[1:5])
            self.regs[a] = v
            return pdu
        if fn == 16:
            a, n, _ = struct.unpack('>HHB', pdu[1:6])
            self.regs[a:a + n] = list(struct.unpack(f'>{n}H', pdu[6:6 + 2 * n]))
            return pdu[:5]
        if fn == 5:
            a, v = struct.unpack('>HH', pdu[1:5])
            self.coils[a] = 1 if v == 0xFF00 else 0
            return pdu
        if fn == 15:
            a, n, _ = struct.unpack('>HHB', pdu[1:6])
            for i in range(n):
                self.coils[a + i] = (pdu[6 + i // 8] >> (i % 8)) & 1
            return pdu[:5]
        return bytes([fn | 0x80, 1])


def rtu_answer(dev, frame):
    if len(frame) < 4 or modbus.crc16(frame[:-2]) != struct.unpack('<H', frame[-2:])[0]:
        return None
    ans = dev.handle(frame[0], frame[1:-2])
    if ans is None or frame[0] == 0:
        return None
    out = bytes([frame[0]]) + ans
    return out + struct.pack('<H', modbus.crc16(out))


def mbap_answer(dev, frame):
    tid, _, _, unit = struct.unpack('>HHHB', frame[:7])
    ans = dev.handle(unit, frame[7:])
    return None if ans is None else struct.pack('>HHHB', tid, 0, len(ans) + 1, unit) + ans


class Servers(unittest.TestCase):
    """The same request set over every network transport."""

    @classmethod
    def setUpClass(cls):
        cls.dev = Device(1)
        dev = cls.dev

        class TcpHandler(socketserver.BaseRequestHandler):
            def handle(self):
                rtu = self.server.rtu
                while True:
                    data = self.request.recv(512)
                    if not data:
                        return
                    ans = rtu_answer(dev, data) if rtu else mbap_answer(dev, data)
                    if ans:
                        self.request.sendall(ans)

        class UdpHandler(socketserver.BaseRequestHandler):
            def handle(self):
                data, sock = self.request
                ans = rtu_answer(dev, data) if self.server.rtu else mbap_answer(dev, data)
                if ans:
                    sock.sendto(ans, self.client_address)

        cls.servers = {}
        for name, cls_, handler, rtu in [('tcp', socketserver.ThreadingTCPServer, TcpHandler, False),
                                          ('rtu_tcp', socketserver.ThreadingTCPServer, TcpHandler, True),
                                          ('udp', socketserver.UDPServer, UdpHandler, False),
                                          ('rtu_udp', socketserver.UDPServer, UdpHandler, True)]:
            cls_.allow_reuse_address = True
            srv = cls_(('127.0.0.1', 0), handler)
            srv.rtu = rtu
            srv.daemon_threads = True
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers[name] = srv

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers.values():
            s.shutdown()
            s.server_close()

    def conn(self, t, timeout=300):
        return {'transport': t, 'host': '127.0.0.1', 'netport': self.servers[t].server_address[1], 'timeout': timeout}

    def test_read_write_exception_timeout_on_every_transport(self):
        for t in self.servers:
            with self.subTest(transport=t):
                self.dev.regs[10:12] = [10, 11]
                self.dev.coils = [0] * 32
                r = modbus.run(self.conn(t), [
                    {'unit': 1, 'fn': 3, 'addr': 5, 'count': 3},
                    {'unit': 1, 'fn': 16, 'addr': 10, 'values': [0x1234, 65535]},
                    {'unit': 1, 'fn': 3, 'addr': 10, 'count': 2},
                    {'unit': 1, 'fn': 6, 'addr': 12, 'values': ['0x7']},
                    {'unit': 1, 'fn': 15, 'addr': 3, 'values': [1, 0, 1]},
                    {'unit': 1, 'fn': 1, 'addr': 0, 'count': 8},
                    {'unit': 1, 'fn': 5, 'addr': 0, 'values': [1]},
                    {'unit': 1, 'fn': 4, 'addr': 0, 'count': 1},
                    {'unit': 1, 'fn': 3, 'addr': 99, 'count': 5},
                    {'unit': 9, 'fn': 3, 'addr': 0, 'count': 1},
                    {'unit': 1, 'fn': 3, 'addr': 0, 'count': 200},
                    {'unit': 1, 'fn': 3, 'addr': 0, 'count': 1},
                ])['results']
                self.assertEqual(r[0]['values'], [5, 6, 7])
                self.assertTrue(r[1]['ok'])
                self.assertEqual(r[2]['values'], [0x1234, 65535])
                self.assertEqual(self.dev.regs[12], 7)
                self.assertEqual(r[5]['values'], [0, 0, 0, 1, 0, 1, 0, 0])
                self.assertEqual(self.dev.coils[0], 1)
                self.assertEqual((r[7]['ok'], r[7]['code']), (False, 1))
                self.assertIn('illegal function', r[7]['error'])
                self.assertEqual(r[8]['code'], 2)
                self.assertIn('timeout', r[9]['error'])
                self.assertIn('Count must be', r[10]['error'])          # validation error, the batch goes on
                self.assertEqual(r[11]['values'], [0])                     # stale answers drained, next request fine
                self.assertTrue(r[0]['tx'] and r[0]['rx'])

    def test_scan(self):
        r = modbus.scan(self.conn('rtu_tcp', 50), 1, 5, 3, 0)
        self.assertEqual([f['unit'] for f in r['found']], [1])
        r = modbus.scan(self.conn('tcp', 50), 1, 3, 4, 0)                # an exception answer counts as found
        self.assertEqual([(f['unit'], f['ok']) for f in r['found']], [(1, False)])
        with self.assertRaises(modbus.ModbusError):
            modbus.scan(self.conn('tcp'), 1, 247)

    def test_connect_error(self):
        with self.assertRaises(modbus.ModbusError) as cm:
            modbus.run({'transport': 'tcp', 'host': '127.0.0.1', 'netport': 1, 'timeout': 100}, [{'unit': 1, 'fn': 3, 'addr': 0, 'count': 1}])
        self.assertEqual(cm.exception.status, 502)


class SerialRtu(unittest.TestCase):
    """RTU over a pseudo terminal: the test thread plays the slave on the master side."""

    def test_serial_rtu(self):
        if modbus.serial is None:
            self.skipTest('pyserial missing')
        master, slave = os.openpty()
        path = os.ttyname(slave)
        dev, stop = Device(3), threading.Event()

        def slave_loop():
            buf = b''
            while not stop.is_set():
                try:
                    chunk = os.read(master, 256)
                except OSError:
                    return
                buf += chunk
                ans = rtu_answer(dev, buf)
                if ans:
                    os.write(master, ans)
                    buf = b''
                elif len(buf) > 64:
                    buf = b''
        threading.Thread(target=slave_loop, daemon=True).start()
        try:
            with mock.patch.object(modbus, '_PORT', modbus.re.compile(r'^/dev/')):
                c = {'transport': 'rtu', 'port': path, 'baud': 115200, 'parity': 'N', 'bytesize': 8, 'stopbits': 1, 'timeout': 300}
                r = modbus.run(c, [{'unit': 3, 'fn': 3, 'addr': 0, 'count': 4}, {'unit': 3, 'fn': 4, 'addr': 0, 'count': 1}])['results']
                self.assertEqual(r[0]['values'], [0, 1, 2, 3])
                self.assertEqual(r[0]['tx'], '03 03 00 00 00 04 45 EB')
                self.assertEqual(r[1]['code'], 1)
                with mock.patch.object(modbus, 'blocked', return_value='A test script is running'):
                    with self.assertRaises(modbus.ModbusError) as cm:
                        modbus.run(c, [{'unit': 3, 'fn': 3, 'addr': 0, 'count': 1}])
                    self.assertEqual(cm.exception.status, 409)
        finally:
            stop.set()
            os.close(slave)
            os.close(master)


class Validation(unittest.TestCase):
    def test_crc(self):
        self.assertEqual(struct.pack('<H', modbus.crc16(bytes.fromhex('010300000010'))), bytes.fromhex('4406'))   # captured from a device

    def test_conn(self):
        self.assertEqual(modbus.check_conn({'transport': 'tcp', 'host': 'plc.local', 'netport': '1502'})['port'], 1502)
        for bad in [{'transport': 'x'}, {'transport': 'rtu', 'port': '/etc/passwd'}, {'transport': 'rtu', 'port': '/dev/ttyUSB0', 'parity': 'X'},
                    {'transport': 'tcp', 'host': 'a b'}, {'transport': 'rtu', 'port': '/dev/ttyUSB0', 'timeout': 1}]:
            with self.subTest(bad=bad), self.assertRaises(modbus.ModbusError):
                modbus.check_conn(bad)

    def test_ops(self):
        self.assertEqual(modbus.pdu_of(modbus.check_op({'unit': 1, 'fn': 5, 'addr': 2, 'values': [1]})), bytes.fromhex('050002FF00'))
        self.assertEqual(modbus.pdu_of(modbus.check_op({'unit': 1, 'fn': 15, 'addr': 0, 'values': [1, 0, 1, 1, 0, 0, 0, 0, 1]})),
                         bytes.fromhex('0F0000000902') + bytes([0b00001101, 1]))
        for bad in [{'fn': 7}, {'fn': 3, 'unit': 0}, {'fn': 3, 'count': 126}, {'fn': 3, 'addr': 65535, 'count': 2},
                    {'fn': 6, 'values': [1, 2]}, {'fn': 6, 'values': [70000]}, {'fn': 5, 'values': [2]}, {'fn': 16, 'values': []}]:
            with self.subTest(bad=bad), self.assertRaises(modbus.ModbusError):
                modbus.check_op(bad)

    def test_profiles_sanitised(self):
        d = modbus.check_profiles({'profiles': [{'name': 'Charger', 'period': 10, 'conn': {'transport': 'rtu', 'port': '/dev/ttyUSB0', 'evil': 1},
                                                 'macros': [{'name': 'x' * 500, 'fn': '3', 'fmt': '<script>', 'cycle': 1}, 'junk']}],
                                   'current': 'nope'})
        p = d['profiles'][0]
        self.assertEqual((d['current'], p['period'], len(p['macros'][0]['name']), p['macros'][0]['fmt']), ('Charger', 50, 60, 'u16'))
        self.assertNotIn('evil', p['conn'])
        self.assertTrue(p['macros'][0]['cycle'])
        self.assertTrue(p['macros'][0]['auto'])                                  # old "cycle" rows become timer rows
        d = modbus.check_profiles({'profiles': [{'name': 'T', 'macros': [{'auto': True, 'period': '20'}, {'auto': False, 'period': 'x'}]}]})
        self.assertEqual(d['profiles'][0]['macros'][0]['period'], 50)
        self.assertNotIn('period', d['profiles'][0]['macros'][1])
        with self.assertRaises(modbus.ModbusError):
            modbus.check_profiles({'profiles': [{'name': 'a'}, {'name': 'a'}]})

    def test_sessions(self):
        c = client(logged_in=True)
        data = {'profile': {'conn': {'transport': 'rtu', 'port': '/dev/ttyUSB0', 'baud': '115200'}, 'period': 300,
                            'macros': [{'name': 'status', 'unit': '1', 'fn': '3', 'addr': '0', 'count': '4', 'fmt': 'u16'}]},
                'results': [{'ok': True, 'values': [0, 1, 5, 1], 'ms': 21}], 'log': [{'t': 1, 'name': 'status'}],
                'found': [{'unit': 1, 'ok': True}], 'note': 'firmware at 4..6 (ascii)'}
        r = c.post('/api/modbus/session/save', json={'name': 'Charger J1772', 'data': data})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()['sessions'][0]['rows'], 1)
        self.assertTrue(os.path.isfile(os.path.join(config.modbus_sessions_dir(), 'Charger_J1772.json')))
        self.assertEqual(c.post('/api/modbus/session/save', json={'name': 'Charger J1772', 'data': data}).status_code, 409)
        data['note'] = 'v2'
        self.assertEqual(c.post('/api/modbus/session/save', json={'name': 'Charger J1772', 'data': data, 'overwrite': True}).status_code, 200)
        d = c.get('/api/modbus/session?name=' + 'Charger J1772').get_json()
        self.assertEqual((d['name'], d['note'], d['profile']['period'], d['results'][0]['values']), ('Charger J1772', 'v2', 300, [0, 1, 5, 1]))
        self.assertEqual(d['profile']['name'], 'Charger J1772')
        for bad in ['', '../x', 'a/b', 'x' * 61]:
            with self.subTest(bad=bad):
                self.assertEqual(c.post('/api/modbus/session/save', json={'name': bad, 'data': data}).status_code, 400)
        self.assertEqual(c.get('/api/modbus/session?name=nope').status_code, 404)
        self.assertEqual(c.post('/api/modbus/session/delete', json={'name': 'Charger J1772'}).get_json()['sessions'], [])
        self.assertEqual(client().get('/api/modbus/sessions').status_code, 401)

    def test_api(self):
        self.assertEqual(client().get('/api/modbus/info').status_code, 401)
        c = client(logged_in=True)
        info = c.get('/api/modbus/info').get_json()
        self.assertIn('ports', info)
        r = c.post('/api/modbus/profiles', json={'profiles': [{'name': 'P1', 'conn': {'transport': 'tcp'}, 'macros': []}], 'current': 'P1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(config.get('modbus')['current'], 'P1')
        self.assertEqual(c.get('/api/modbus/info').get_json()['profiles'][0]['name'], 'P1')
        self.assertEqual(c.post('/api/modbus/request', json={'conn': {'transport': 'rtu', 'port': '/bad'}, 'ops': [{}]}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
