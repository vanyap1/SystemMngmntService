"""core.net: CAN frame parsing and interface name validation (no hardware needed)."""
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
