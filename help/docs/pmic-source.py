#!/usr/bin/env python3
"""Print RK809/RK817 power-on / power-off source registers (read-only).

Run right after a boot to see WHY the PMIC switched on last time.
"""
import os
import fcntl

BUS, ADDR, I2C_SLAVE_FORCE = '/dev/i2c-0', 0x20, 0x0706
ON_BITS = {7: 'PWRON key', 6: 'plug-in (VCC rising)', 5: 'RTC alarm',
           4: 'restart', 3: 'bit3', 2: 'bit2', 1: 'bit1', 0: 'bit0'}

fd = os.open(BUS, os.O_RDWR)
fcntl.ioctl(fd, I2C_SLAVE_FORCE, ADDR)


def rd(reg):
    os.write(fd, bytes([reg]))
    return os.read(fd, 1)[0]


on, off = rd(0xF5), rd(0xF6)
os.close(fd)
print(f'ON_SOURCE  0xF5 = 0x{on:02x}  ->', ', '.join(v for b, v in ON_BITS.items() if on >> b & 1) or '-')
print(f'OFF_SOURCE 0xF6 = 0x{off:02x}')
