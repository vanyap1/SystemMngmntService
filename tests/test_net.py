"""core.net: CAN frame parsing, per-ID statistics and interface name validation (no hardware needed)."""
import unittest

from tests.support import app  # noqa: F401  (project path)
from core import net


class ParseFrame(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(net.parse_frame('123', data='11 22:33'), (0x123, 3, b'\x11\x22\x33'))

    def test_extended_is_automatic_above_11_bits(self):
        raw, dlc, data = net.parse_frame('0x18FF50E5', data='')
        self.assertEqual(raw, 0x18FF50E5 | net.CAN_EFF_FLAG)
        self.assertEqual((dlc, data), (0, b''))
        self.assertTrue(net.parse_frame('800')[0] & net.CAN_EFF_FLAG)

    def test_rtr_keeps_dlc_without_payload(self):
        raw, dlc, data = net.parse_frame('7FF', rtr=True, data='0102')
        self.assertEqual((raw, dlc, data), (0x7FF | net.CAN_RTR_FLAG, 2, b''))

    def test_invalid_input(self):
        for args in [('xyz',), ('20000000', True), ('1', False, False, '123'), ('1', False, False, 'zz'),
                     ('1', False, False, '00' * 9)]:
            with self.subTest(args=args):
                with self.assertRaises(net.NetError):
                    net.parse_frame(*args)


class IdStatistics(unittest.TestCase):
    """Per-ID rows (PCAN-View-like list) are counted by the reader, independent of the frame buffer."""

    def setUp(self):
        self.bus = net.CanBus('vcan-test')     # no socket: _record is fed directly

    def test_count_cycle_and_since(self):
        for i, t in enumerate([10.0, 10.1, 10.2, 10.35]):
            self.bus._record('rx', 0x123, 2, bytes([i, 0]), t=t)
        self.bus._record('rx', 0x18FF50E5 | net.CAN_EFF_FLAG, 0, b'', t=10.4)
        self.bus._record('tx', 0x123, 1, b'\x01', t=10.5)
        self.bus._record('err', 0x020, 8, bytes(8), 'no ACK', t=10.6)
        d = self.bus.frames()
        rows = {r['key']: r for r in d['ids']}
        self.assertEqual(len(rows), 4)
        r = rows['rx:s:123']
        self.assertEqual((r['count'], r['data'], r['dlc']), (4, '0300', 2))
        self.assertAlmostEqual(r['period'], 0.15)
        self.assertAlmostEqual(r['min'], 0.1)
        self.assertAlmostEqual(r['max'], 0.15)
        self.assertTrue(0.1 < r['avg'] < 0.15)
        self.assertTrue(rows['rx:x:18ff50e5']['ext'])
        self.assertEqual(d['totals'], {'rx': 5, 'tx': 1, 'err': 1, 'rp': 0, 'dropped_ids': 0})
        # only rows touched after `since`
        self.bus._record('rx', 0x123, 2, b'\x09\x09', t=10.7)
        self.assertEqual([r['key'] for r in self.bus.frames(d['next'])['ids']], ['rx:s:123'])

    def test_survives_buffer_overflow_and_clear(self):
        n = net.CanBus.MAX_FRAMES + 500
        for i in range(n):
            self.bus._record('rx', 0x7FF, 0, b'', t=i / 1000)
        d = self.bus.frames()
        self.assertEqual(len(d['frames']), net.CanBus.MAX_FRAMES)
        self.assertEqual(d['ids'][0]['count'], n)
        self.bus.clear()
        d = self.bus.frames()
        self.assertEqual((d['ids'], d['totals']['rx']), ([], 0))

    def test_id_limit(self):
        self.bus.MAX_IDS = 3
        for cid in range(5):
            self.bus._record('rx', cid, 0, b'')
        d = self.bus.frames()
        self.assertEqual((len(d['ids']), d['totals']['dropped_ids'], d['totals']['rx']), (3, 2, 5))

    def test_kernel_timestamp(self):
        import socket
        import struct
        lvl = socket.SOL_SOCKET
        self.assertAlmostEqual(net.CanBus._stamp([(lvl, net.SO_TIMESTAMP, struct.pack('=qq', 100, 250000))]), 100.25)
        self.assertAlmostEqual(net.CanBus._stamp([(lvl, net.SO_TIMESTAMP, struct.pack('=ii', 7, 500000))]), 7.5)
        self.assertIsNone(net.CanBus._stamp([]))


class Interfaces(unittest.TestCase):
    def test_check_iface(self):
        self.assertEqual(net.check_iface('lo'), 'lo')
        for name in ['../etc', 'lo; reboot', 'nonexistent0', '']:
            with self.subTest(name=name):
                with self.assertRaises(net.NetError):
                    net.check_iface(name)
        with self.assertRaises(net.NetError):
            net.check_iface('lo', can=True)

    def test_interfaces_list(self):
        names = [i['name'] for i in net.interfaces()]
        self.assertIn('lo', names)


if __name__ == '__main__':
    unittest.main()
