"""testPlatform/instruments/modbus.py: RTU on a pseudo terminal, Modbus TCP / UDP and RTU over TCP on localhost.

A simulated slave answers — no real serial port or Modbus device is used.
"""
import os
import socket
import struct
import sys
import threading
import time
import tty
import unittest

from tests.support import ROOT

sys.path.insert(0, os.path.join(ROOT, 'testPlatform'))
from instruments.modbus import (ModbusError, ModbusException, ModbusRTU, ModbusRTUoverTCP, ModbusTCP,  # noqa: E402
                                ModbusUDP, crc16, from_float32, from_u32, to_ascii, to_float32, to_s16, to_s32,
                                to_u32)


class Slave:
    """Register / coil memory of one unit; ``pdu(unit, pdu)`` → answer PDU or None (not addressed / silent)."""

    def __init__(self, unit=1):
        self.unit = unit
        self.regs = [0] * 100
        self.regs[4:6] = [0x332E, 0x3437]                  # "3.47"
        self.coils = [0] * 32
        self.requests = []
        self.silent = 0                                    # ignore the next n requests (timeout + retry)

    def pdu(self, unit, pdu):
        self.requests.append((unit, pdu))
        if unit not in (self.unit, 0):
            return None
        if self.silent:
            self.silent -= 1
            return None
        fn = pdu[0]
        if fn in (1, 2, 3):
            addr, n = struct.unpack('>HH', pdu[1:5])
            if addr + n > 100:
                return bytes([fn | 0x80, 2])
            if fn == 3:
                return bytes([3, 2 * n]) + b''.join(struct.pack('>H', r) for r in self.regs[addr:addr + n])
            bits = self.coils[addr:addr + n]
            data = bytearray((n + 7) // 8)
            for i, b in enumerate(bits):
                data[i // 8] |= b << (i % 8)
            return bytes([fn, len(data)]) + bytes(data)
        if fn == 5:
            addr, v = struct.unpack('>HH', pdu[1:5])
            self.coils[addr] = 1 if v == 0xFF00 else 0
            return pdu
        if fn == 6:
            addr, v = struct.unpack('>HH', pdu[1:5])
            self.regs[addr] = v
            return pdu
        if fn == 15:
            addr, n = struct.unpack('>HH', pdu[1:5])
            for i in range(n):
                self.coils[addr + i] = (pdu[6 + i // 8] >> (i % 8)) & 1
            return pdu[:5]
        if fn == 16:
            addr, n = struct.unpack('>HH', pdu[1:5])
            self.regs[addr:addr + n] = struct.unpack(f'>{n}H', pdu[6:6 + 2 * n])
            return pdu[:5]
        return bytes([fn | 0x80, 1])


def rtu_frame(unit, pdu):
    f = bytes([unit]) + pdu
    return f + struct.pack('<H', crc16(f))


def rtu_split(buf):
    """Whole request frames at the start of buf (requests have known lengths)."""
    frames = []
    while len(buf) >= 8:
        n = 9 + buf[6] if buf[1] in (15, 16) else 8
        if len(buf) < n:
            break
        frames.append(buf[:n])
        buf = buf[n:]
    return frames, buf


class Rtu(unittest.TestCase):
    def setUp(self):
        self.master, slave_fd = os.openpty()
        tty.setraw(slave_fd)
        self.path = os.ttyname(slave_fd)
        self.slave_fd = slave_fd
        self.slave = Slave()
        self.corrupt = 0
        self.stop = False
        threading.Thread(target=self._serve, daemon=True).start()
        self.mb = ModbusRTU(self.path, 115200, unit=1, timeout=0.3)

    def _serve(self):
        buf = b''
        while not self.stop:
            try:
                buf += os.read(self.master, 512)
            except OSError:
                return
            frames, buf = rtu_split(buf)
            for f in frames:
                if crc16(f[:-2]) != struct.unpack('<H', f[-2:])[0]:
                    continue
                ans = self.slave.pdu(f[0], f[1:-2])
                if ans is None or f[0] == 0:
                    continue
                out = rtu_frame(f[0], ans)
                if self.corrupt:
                    self.corrupt -= 1
                    out = out[:-1] + bytes([out[-1] ^ 0xFF])
                os.write(self.master, out)

    def tearDown(self):
        self.stop = True
        self.mb.close()
        os.close(self.slave_fd)
        os.close(self.master)

    def test_read_write_registers_and_coils(self):
        regs = self.mb.readHolding(0, 8)
        self.assertEqual(to_ascii(regs[4:6]), '3.47')
        self.assertEqual(self.mb.last['tx'], '01 03 00 00 00 08 44 0C')
        self.assertTrue(self.mb.last['rx'].startswith('01 03 10'))
        self.mb.writeRegister(10, -2)
        self.mb.writeRegisters(20, from_float32(1.5) + from_u32(70000))
        self.assertEqual(self.slave.regs[10], 0xFFFE)
        r = self.mb.readHolding(20, 4)
        self.assertEqual((to_float32(r[:2]), to_u32(r[2:])), ([1.5], [70000]))
        self.mb.writeCoil(3, 1)
        self.mb.writeCoils(8, [1, 0, 1, 1, 0, 0, 0, 0, 1])
        self.assertEqual(self.mb.readCoils(0, 17), [0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1])
        self.assertEqual(self.mb.readDiscrete(3, 1), [1])

    def test_exception_timeout_retry_crc(self):
        with self.assertRaises(ModbusException) as cm:
            self.mb.readHolding(98, 5)
        self.assertEqual(cm.exception.code, 2)
        with self.assertRaises(ModbusException) as cm:
            self.mb.readInput(0, 1)                      # fn 04 not supported by this slave
        self.assertEqual(cm.exception.code, 1)
        with self.assertRaisesRegex(ModbusError, 'timeout'):
            self.mb.readHolding(0, 1, unit=7)            # nobody there
        self.slave.silent = 1
        self.mb.retries = 1
        self.assertEqual(self.mb.readHolding(4, 1), [0x332E])     # first request lost, the retry answers
        self.corrupt = 1
        self.mb.retries = 0
        with self.assertRaisesRegex(ModbusError, 'CRC'):
            self.mb.readHolding(0, 1)
        self.assertEqual(self.mb.readHolding(4, 1), [0x332E])     # the line works again

    def test_broadcast_scan_and_raw_request(self):
        self.assertIsNone(self.mb.request(6, struct.pack('>HH', 30, 9), unit=0))
        time.sleep(0.05)
        self.assertEqual(self.slave.regs[30], 9)
        self.assertEqual(self.mb.scan(1, 3, timeout=0.05), [1])
        self.assertEqual(self.mb.request(3, struct.pack('>HH', 4, 1)), b'\x02\x33\x2e')
        with self.assertRaises(ValueError):
            self.mb.readHolding(0, 126)

    def test_port_is_exclusive_and_errors_are_readable(self):
        self.mb.readHolding(0, 1)
        other = ModbusRTU(self.path, 115200)
        with self.assertRaisesRegex(ModbusError, 'cannot open'):
            other.readHolding(0, 1)
        with self.assertRaisesRegex(ModbusError, 'cannot open /dev/nonexistent'):
            ModbusRTU('/dev/nonexistent').readHolding(0, 1)


class Formats(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual(to_s16([1, 0xFFFF, 0x8000]), [1, -1, -32768])
        self.assertEqual(to_u32([1, 2]), [0x10002])
        self.assertEqual(to_u32([1, 2], swap=True), [0x20001])
        self.assertEqual(to_s32(from_u32(-5 & 0xFFFFFFFF)), [-5])
        self.assertEqual(to_float32(from_float32(-2.25, swap=True), swap=True), [-2.25])
        self.assertEqual(to_ascii([0x204A, 0x3137, 0x3732, 0x5F30, 0]), ' J1772_0')
        self.assertEqual(to_ascii([0x4A20], swap_bytes=True), ' J')


class Sockets(unittest.TestCase):
    """Modbus TCP, RTU over TCP and UDP against servers on localhost."""

    def setUp(self):
        self.slave = Slave()
        self.socks = []

    def tearDown(self):
        for s in self.socks:
            s.close()

    def _tcp(self, rtu):
        srv = socket.socket()
        srv.bind(('127.0.0.1', 0))
        srv.listen(2)
        self.socks.append(srv)

        def serve():
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                with conn:
                    buf = b''
                    while True:
                        try:
                            data = conn.recv(512)
                        except OSError:
                            break
                        if not data:
                            break
                        buf += data
                        if rtu:
                            frames, buf = rtu_split(buf)
                            for f in frames:
                                ans = self.slave.pdu(f[0], f[1:-2])
                                if ans is not None:
                                    conn.sendall(rtu_frame(f[0], ans))
                            continue
                        while len(buf) >= 7 and len(buf) >= 6 + struct.unpack('>H', buf[4:6])[0]:
                            n = 6 + struct.unpack('>H', buf[4:6])[0]
                            tid, _, _, unit = struct.unpack('>HHHB', buf[:7])
                            ans = self.slave.pdu(unit, buf[7:n])
                            buf = buf[n:]
                            if ans is not None:
                                conn.sendall(struct.pack('>HHHB', tid, 0, len(ans) + 1, unit) + ans)
                            if unit == 9:                # drops the connection after answering
                                conn.close()
                                break
        threading.Thread(target=serve, daemon=True).start()
        return srv.getsockname()[1]

    def test_tcp_and_reconnect(self):
        port = self._tcp(rtu=False)
        mb = ModbusTCP('127.0.0.1', port, timeout=1)
        self.assertEqual(to_ascii(mb.readHolding(4, 2)), '3.47')
        self.assertTrue(mb.last['tx'].startswith('00 01 00 00 00 06 01 03'))
        mb.writeRegister(1, 5)
        self.slave.unit = 9
        with self.assertRaises(ModbusException):
            mb.readHolding(98, 5, unit=9)                # answered, then the peer closes
        self.slave.unit = 1
        self.assertEqual(mb.readHolding(1, 1), [5])      # reconnected by itself
        mb.close()

    def test_rtu_over_tcp(self):
        mb = ModbusRTUoverTCP('127.0.0.1', self._tcp(rtu=True), timeout=1)
        mb.writeRegisters(0, [7, 8])
        self.assertEqual(mb.readHolding(0, 2), [7, 8])
        self.assertTrue(mb.last['tx'].startswith('01 03 00 00 00 02'))
        mb.close()

    def test_udp(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        srv.bind(('127.0.0.1', 0))
        self.socks.append(srv)

        def serve():
            while True:
                try:
                    data, peer = srv.recvfrom(512)
                except OSError:
                    return
                tid, _, _, unit = struct.unpack('>HHHB', data[:7])
                ans = self.slave.pdu(unit, data[7:])
                if ans is not None:
                    srv.sendto(struct.pack('>HHHB', tid, 0, len(ans) + 1, unit) + ans, peer)
        threading.Thread(target=serve, daemon=True).start()
        mb = ModbusUDP('127.0.0.1', srv.getsockname()[1], timeout=0.5)
        self.assertEqual(mb.readHolding(4, 1), [0x332E])
        with self.assertRaisesRegex(ModbusError, 'timeout'):
            mb.readHolding(0, 1, unit=5)
        with self.assertRaisesRegex(ModbusError, 'cannot connect'):
            ModbusTCP('127.0.0.1', 1, timeout=0.3).readHolding(0, 1)
        mb.close()


if __name__ == '__main__':
    unittest.main()
