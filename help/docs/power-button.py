#!/usr/bin/env python3
"""Power button daemon.

Watches one GPIO line (button pulls it HIGH while pressed). When the line stays
high for PB_HOLD seconds the system is powered off with `systemctl poweroff`.

Safety: the daemon is armed only after it has seen the line LOW at least once,
so a stuck/miswired button can never cause a shutdown loop at boot.

Settings (environment, see /etc/default/power-button):
  PB_CHIP   gpiochip name or path        (default gpiochip4)
  PB_LINE   line offset on the chip      (default 0)
  PB_HOLD   seconds to hold the button   (default 1.0)
  PB_ACTION systemctl verb               (default poweroff; e.g. reboot)
"""
import os
import sys
import time
import subprocess

import gpiod

CHIP = os.environ.get('PB_CHIP', 'gpiochip4')
LINE = int(os.environ.get('PB_LINE', '0'))
HOLD = float(os.environ.get('PB_HOLD', '1.0'))
ACTION = os.environ.get('PB_ACTION', 'poweroff')
POLL = 0.02


def log(msg):
    print(msg, flush=True)


def request_line():
    chip = gpiod.Chip(CHIP)
    line = chip.get_line(LINE)
    flags = getattr(gpiod, 'LINE_REQ_FLAG_BIAS_PULL_DOWN', 0)
    try:
        line.request(consumer='power-button', type=gpiod.LINE_REQ_EV_BOTH_EDGES, flags=flags)
    except OSError:
        # Bias not supported by this chip/kernel: rely on the external pull-down.
        line.request(consumer='power-button', type=gpiod.LINE_REQ_EV_BOTH_EDGES)
    return chip, line


def drain(line):
    while line.event_wait(sec=0, nsec=0):
        line.event_read_multiple()


def held_long_enough(line):
    """Line went high: True if it stays high for HOLD seconds."""
    t0 = time.monotonic()
    while line.get_value() == 1:
        if time.monotonic() - t0 >= HOLD:
            return True
        time.sleep(POLL)
    return False


def main():
    chip, line = request_line()
    armed = line.get_value() == 0
    log(f'power-button: {CHIP} line {LINE}, hold {HOLD}s -> systemctl {ACTION}'
        + ('' if armed else ' (line is HIGH at start, waiting for release)'))
    while True:
        if line.event_wait(sec=30):
            drain(line)
        level = line.get_value()
        if not armed:
            if level == 0:
                armed = True
                log('power-button: line released, armed')
            continue
        if level == 1 and held_long_enough(line):
            log(f'power-button: pressed for {HOLD}s, running systemctl {ACTION}')
            subprocess.run(['systemctl', ACTION], check=False)
            time.sleep(3600)        # systemd stops us during shutdown
            return 0


if __name__ == '__main__':
    sys.exit(main())
