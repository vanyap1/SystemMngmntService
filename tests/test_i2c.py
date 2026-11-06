"""I²C tools (core/i2c.py, /api/i2c/*) on the simulated bus of tests/fake_i2c.py — no real bus is touched."""
import unittest

from tests.support import client, config  # noqa: F401  (support first)
from core import i2c
from core.i2c import I2CError
from tests import fake_i2c
from tests.fake_i2c import BUS


class Parsing(unittest.TestCase):
    def test_parse_detect(self):
        fake = fake_i2c.FakeBus()
        found, busy = i2c.parse_detect(fake._detect())
        self.assertEqual(found, [0x25, 0x40, 0x41, 0x50])
        self.assertEqual(busy, [0x68])

    def test_parse_bytes(self):
        self.assertEqual(i2c.parse_bytes('C3,83'), [0xc3, 0x83])
        self.assertEqual(i2c.parse_bytes('0x01 0xff;7'), [1, 255, 7])
        self.assertEqual(i2c.parse_bytes([1, '0x2']), [1, 2])
        for bad in ('', 'zz', '100', '1 -1', [256], ' '.join(['1'] * 257)):
            with self.subTest(bad=bad), self.assertRaises(I2CError):
                i2c.parse_bytes(bad)

    def test_validation(self):
        for addr in (0, 2, 0x78, 0x7f, '0x100', 'x', True, None):
            with self.subTest(addr=addr), self.assertRaises(I2CError):
                i2c.check_addr(addr)
        self.assertEqual(i2c.check_addr('0x41'), 0x41)
        self.assertEqual(i2c.check_reg('0x1234', 2), (0x1234, 2))
        self.assertEqual(i2c.check_reg('zz', 0), (None, 0))
        with self.assertRaises(I2CError):
            i2c.check_reg(0x100, 1)
        with self.assertRaises(I2CError):
            i2c.check_reg(0, 3)

    def test_hint(self):
        self.assertIn('EEPROM', i2c.hint(0x50))
        self.assertEqual(i2c.hint(0x10), '')

    def test_friendly_errors(self):
        self.assertIn('No ACK', i2c._friendly('Error: Sending messages failed: Remote I/O error'))
        self.assertIn('Force', i2c._friendly('Error: Could not set address to 0x68: Device or resource busy'))


class FakeBusApi(unittest.TestCase):
    def setUp(self):
        self.fake, self.restore = fake_i2c.install()
        self._labels = config.CFG.get('i2c_labels')
        self.c = client(logged_in=True)

    def tearDown(self):
        self.restore()
        config.CFG['i2c_labels'] = self._labels or {}

    def post(self, url, **body):
        return self.c.post('/api/i2c/' + url, json=body)

    def test_buses_list_does_not_touch_the_bus(self):
        d = self.c.get('/api/i2c/buses').get_json()
        self.assertEqual([b['bus'] for b in d['buses']], [BUS])
        self.assertEqual([c['addr'] for c in d['buses'][0]['clients']], [0x21, 0x68])
        self.assertEqual(self.fake.calls, [])

    def test_scan(self):
        d = self.post('scan', bus=BUS).get_json()
        self.assertEqual((d['found'], d['busy']), ([0x25, 0x40, 0x41, 0x50], [0x68]))
        self.assertEqual(self.fake.calls[-1][:2], ['i2cdetect', '-y'])
        self.post('scan', bus=BUS, mode='quick')
        self.assertIn('-q', self.fake.calls[-1])
        self.assertEqual(self.post('scan', bus=BUS, mode='evil').status_code, 400)
        self.assertEqual(self.post('scan', bus=3).status_code, 404)        # no such node

    def test_read_register(self):
        d = self.post('read', bus=BUS, addr='0x41', reg='0x00', width=1, length=2).get_json()
        self.assertEqual(d['data'], [0xc3, 0x83])
        self.assertEqual(self.fake.calls[-1], ['i2ctransfer', '-y', str(BUS), 'w1@0x41', '0x00', 'r2'])

    def test_read_16bit_register_and_raw(self):
        d = self.post('read', bus=BUS, addr=0x50, reg='0x0102', width=2, length=3).get_json()
        self.assertEqual(d['data'], [(0x102 * 7) & 0xff, (0x103 * 7) & 0xff, (0x104 * 7) & 0xff])
        self.assertEqual(self.fake.calls[-1][3:6], ['w2@0x50', '0x01', '0x02'])
        d = self.post('read', bus=BUS, addr=0x25, width=0, length=1).get_json()
        self.assertEqual(self.fake.calls[-1][3:], ['r1@0x25'])
        self.assertEqual(len(d['data']), 1)

    def test_write_then_read(self):
        r = self.post('write', bus=BUS, addr=0x25, reg=0x10, width=1, data='aa bb')
        self.assertEqual(r.get_json()['written'], 2)
        self.assertEqual(self.fake.calls[-1][3:], ['w3@0x25', '0x10', '0xaa', '0xbb'])
        self.assertEqual(self.post('read', bus=BUS, addr=0x25, reg=0x10, length=2).get_json()['data'], [0xaa, 0xbb])

    def test_errors(self):
        r = self.post('read', bus=BUS, addr=0x30, length=1)
        self.assertEqual(r.status_code, 400)
        self.assertIn('No ACK', r.get_json()['error'])
        r = self.post('read', bus=BUS, addr=0x68, length=1)
        self.assertIn('Force', r.get_json()['error'])
        self.assertEqual(self.post('read', bus=BUS, addr=0x68, length=1, force=True).get_json()['data'], [0x45])
        self.assertEqual(self.post('read', bus=BUS, addr=0x25, length=0).status_code, 400)
        self.assertEqual(self.post('write', bus=BUS, addr=0x25, data='').status_code, 400)
        self.assertEqual(self.post('read', bus=BUS, addr='0x25; reboot').status_code, 400)

    def test_force_must_be_true_boolean(self):
        self.post('read', bus=BUS, addr=0x68, length=1, force='yes')
        self.assertNotIn('-f', self.fake.calls[-1] if self.fake.calls else [])

    def test_locked_while_test_runs(self):
        saved = i2c.blocked
        i2c.blocked = lambda: 'A test script is running — I²C access is locked'
        try:
            for url, body in (('scan', {}), ('read', {'addr': 0x25}), ('write', {'addr': 0x25, 'data': '1'})):
                with self.subTest(url=url):
                    self.assertEqual(self.post(url, bus=BUS, **body).status_code, 409)
        finally:
            i2c.blocked = saved
        self.assertEqual(self.fake.calls, [])

    def test_labels(self):
        self.assertEqual(self.post('label', bus=BUS, addr=0x41, label='  INA228   power (EXT1) ').get_json()['label'],
                         'INA228 power (EXT1)')
        self.assertEqual(self.c.get('/api/i2c/buses').get_json()['buses'][0]['labels'], {'0x41': 'INA228 power (EXT1)'})
        self.assertIn(str(BUS), config._FILE['hosts'][config.HOSTNAME]['i2c_labels'])
        self.post('label', bus=BUS, addr=0x41, label='')
        self.assertEqual(self.c.get('/api/i2c/buses').get_json()['buses'][0]['labels'], {})

    def test_login_required(self):
        anon = client()
        self.assertEqual(anon.get('/api/i2c/buses').status_code, 401)
        for url in ('scan', 'read', 'write', 'label'):
            self.assertEqual(anon.post('/api/i2c/' + url, json={'bus': BUS}).status_code, 401)
        self.assertEqual(self.fake.calls, [])


if __name__ == '__main__':
    unittest.main()
