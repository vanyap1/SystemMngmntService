"""Simulated I²C bus for tests and `tests/devserver.py --fake-i2c`: replaces i2c-tools and the sysfs bus list,
so no real bus is ever scanned or written.

Bus 7 ("fake-i2c"): 0x25 unknown chip, 0x40/0x41 INA228-like power monitors, 0x50 24C32 EEPROM (16-bit register
address), 0x68 RTC bound to a kernel driver ("UU"), and a client declared at 0x21 that does not answer.
"""
import re

from core import i2c

BUS = 7


class FakeBus:
    def __init__(self):
        self.devices = {                       # addr -> {'mem': {reg: byte}, 'width': reg address bytes, 'ptr': 0}
            0x25: {'mem': {i: i for i in range(256)}, 'width': 1},
            0x40: {'mem': {0x00: 0x3f, 0x01: 0xff, 0x3e: 0x54, 0x3f: 0x49}, 'width': 1},
            0x41: {'mem': {0x00: 0xc3, 0x01: 0x83, 0x3e: 0x54, 0x3f: 0x49}, 'width': 1},
            0x50: {'mem': {i: (i * 7) & 0xff for i in range(4096)}, 'width': 2},
            0x68: {'mem': {0x00: 0x45, 0x01: 0x59, 0x02: 0x12}, 'width': 1},
        }
        for d in self.devices.values():
            d['ptr'] = 0
        self.busy = {0x68}
        self.calls = []

    def run(self, args):
        self.calls.append(args)
        if args[0] == 'i2cdetect':
            return self._detect()
        return self._transfer(args[1:])

    def _detect(self):
        lines = ['     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f']
        for row in range(0, 0x80, 16):
            cells = []
            for a in range(row, row + 16):
                if a < i2c.ADDR_MIN or a > i2c.ADDR_MAX:
                    cells.append('  ')
                elif a in self.busy:
                    cells.append('UU')
                elif a in self.devices:
                    cells.append(f'{a:02x}')
                else:
                    cells.append('--')
            lines.append(f'{row:02x}: ' + ' '.join(cells) + ' ')
        return '\n'.join(lines) + '\n'

    def _transfer(self, args):
        force = '-f' in args
        args = [a for a in args if a not in ('-y', '-f')]
        bus, rest = args[0], args[1:]
        assert int(bus) == BUS, bus
        out, addr, i = [], None, 0
        while i < len(rest):
            m = re.fullmatch(r'([rw])(\d+)(?:@(0x[0-9a-f]+))?', rest[i])
            kind, n = m.group(1), int(m.group(2))
            addr = int(m.group(3), 16) if m.group(3) else addr
            i += 1
            dev = self.devices.get(addr)
            if addr in self.busy and not force:
                raise i2c.I2CError(i2c._friendly(f'Error: Could not set address to 0x{addr:02x}: Device or resource busy'))
            if dev is None:
                raise i2c.I2CError(i2c._friendly('Error: Sending messages failed: Remote I/O error'))
            if kind == 'w':
                data = [int(x, 16) for x in rest[i:i + n]]
                i += n
                w = dev['width']
                dev['ptr'] = data[0] if w == 1 else (data[0] << 8 | data[1])
                for b in data[w:]:
                    dev['mem'][dev['ptr']] = b
                    dev['ptr'] += 1
            else:
                for _ in range(n):
                    out.append(dev['mem'].get(dev['ptr'], 0xff))
                    dev['ptr'] += 1
        return ' '.join(f'0x{b:02x}' for b in out) + ('\n' if out else '')


def install():
    """Patch core.i2c to use a new FakeBus. Returns (fake, restore)."""
    fake = FakeBus()
    saved = (i2c._run, i2c._node_exists, i2c.udev.i2c_buses, i2c.tools_available)
    i2c._run = fake.run
    i2c._node_exists = lambda bus: int(bus) == BUS
    i2c.udev.i2c_buses = lambda: [{'bus': BUS, 'name': 'fake-i2c', 'node': f'/dev/i2c-{BUS}', 'clients': [
        {'addr': '0x21', 'name': 'pcf8574', 'driver': ''},
        {'addr': '0x68', 'name': 'ds3231', 'driver': 'rtc-ds1307'}]}]
    i2c.tools_available = lambda: True

    def restore():
        i2c._run, i2c._node_exists, i2c.udev.i2c_buses, i2c.tools_available = saved
    return fake, restore
