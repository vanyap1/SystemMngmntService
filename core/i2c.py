"""I²C tools for the HW Utils popup: scan a bus, read / write bytes of a device register (i2c-tools).

Nothing touches a bus on its own: the bus list comes from sysfs (``udev.i2c_buses()``), and ``scan`` / ``read`` /
``write`` run only on an explicit user action. Commands are ``i2cdetect`` (scan) and ``i2ctransfer`` (combined
write-register + repeated-start read, so 8/16-bit register addresses and multi-byte reads work on any device).
Every argument is validated before it reaches the command line; one lock serialises bus access.

Results: ``scan`` → {bus, found: [addr], busy: [addr]} (busy = "UU", bound to a kernel driver; reading or writing
those needs ``force``). ``read`` → {data: [bytes]}, ``write`` → {written: n}.
"""
import os
import re
import shutil
import subprocess
import threading

from core import config, udev

ADDR_MIN, ADDR_MAX = 0x03, 0x77          # i2cdetect / i2ctransfer default range (no reserved addresses)
MAX_LEN = 256
TIMEOUT = 10
SCAN_MODES = {'auto': [], 'quick': ['-q'], 'read': ['-r']}

# Typical chips per address — only a hint for devices that answer but have no name.
HINTS = [
    ((0x20, 0x27), 'PCF8574 / MCP23017 / TCA9555 I/O expander'),
    ((0x38, 0x3b), 'PCF8574A I/O expander, AHT20 (0x38)'),
    ((0x3c, 0x3d), 'SSD1306 / SH1106 OLED display'),
    ((0x40, 0x4f), 'INA219 / INA226 / INA228 power monitor, PCA9685 PWM, HDC1080 (0x40)'),
    ((0x48, 0x4b), 'ADS1115 ADC, TMP102 / LM75 temperature sensor'),
    ((0x50, 0x57), '24Cxx EEPROM'),
    ((0x5a, 0x5a), 'MLX90614 IR thermometer, MPR121 touch'),
    ((0x60, 0x61), 'MCP4725 DAC, SI5351 clock'),
    ((0x68, 0x69), 'DS1307 / DS3231 / PCF8523 RTC, MPU6050 IMU'),
    ((0x70, 0x70), 'TCA9548A I²C multiplexer, HT16K33'),
    ((0x76, 0x77), 'BME280 / BMP280 / MS5611 pressure sensor'),
]


class I2CError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


# Set by routes (e.g. "a test script is running") — returns a reason string to refuse bus access, or None.
blocked = lambda: None   # noqa: E731
_lock = threading.Lock()


def _tool(name):
    return shutil.which(name) or next((p for p in (f'/usr/sbin/{name}', f'/sbin/{name}') if os.path.exists(p)), None)


def tools_available():
    return bool(_tool('i2cdetect') and _tool('i2ctransfer'))


def _run(args):
    """Run an i2c-tools command (argv list). Returns stdout; raises I2CError with the tool's message."""
    exe = _tool(args[0])
    if not exe:
        raise I2CError('i2c-tools are not installed (apt install i2c-tools / install.sh --components devices)', 501)
    cmd = [exe] + args[1:]
    if os.geteuid() != 0:
        node = next((a for a in args[1:] if a.isdigit()), None)
        if node and _node_exists(node) and not os.access(f'/dev/i2c-{node}', os.R_OK | os.W_OK):
            cmd = ['sudo', '-n'] + cmd
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise I2CError('The bus did not answer in time (stuck SDA/SCL?)', 504)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout).strip().splitlines()
        raise I2CError(_friendly(msg[-1] if msg else f'{args[0]} failed'))
    return res.stdout


def _friendly(msg):
    msg = re.sub(r'^Error:\s*', '', msg)
    if 'Remote I/O error' in msg or 'No such device or address' in msg:
        return 'No ACK — the device did not answer (Remote I/O error)'
    if 'Device or resource busy' in msg:
        return 'Address is used by a kernel driver — enable Force to access it anyway'
    if 'Permission denied' in msg or 'sudo' in msg:
        return 'Permission denied on the I²C device node'
    return msg


# ── validation ───────────────────────────────────────────────────────────

def _int(value, what, lo, hi):
    try:
        v = int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        raise I2CError(f'Bad {what}')
    if isinstance(value, bool) or not lo <= v <= hi:
        raise I2CError(f'{what} must be {lo:#x}…{hi:#x}')
    return v


def _node_exists(bus):
    return os.path.exists(f'/dev/i2c-{bus}')


def check_bus(bus):
    b = _int(bus, 'bus', 0, 1023)
    if not _node_exists(b):
        raise I2CError(f'/dev/i2c-{b} does not exist (is the i2c-dev module loaded?)', 404)
    return b


def check_addr(addr):
    return _int(addr, 'address', ADDR_MIN, ADDR_MAX)


def check_reg(reg, width):
    width = _int(width, 'register width', 0, 2)
    if width == 0:
        return None, 0
    return _int(reg, 'register', 0, 0xff if width == 1 else 0xffff), width


def parse_bytes(text):
    """'C3,83' / '0xc3 0x83' / [195, 131] -> [0xc3, 0x83]."""
    if isinstance(text, list):
        items = text
    else:
        items = [t for t in re.split(r'[\s,;]+', str(text or '').strip()) if t]
    out = []
    for t in items:
        if isinstance(t, str):
            t = t.lower()
            t = t if t.startswith('0x') else '0x' + t
        out.append(_int(t, 'data byte', 0, 0xff))
    if not out:
        raise I2CError('No data bytes')
    if len(out) > MAX_LEN:
        raise I2CError(f'At most {MAX_LEN} bytes')
    return out


def _reg_bytes(reg, width):
    return [] if width == 0 else ([reg] if width == 1 else [reg >> 8, reg & 0xff])


def _guard():
    why = blocked()
    if why:
        raise I2CError(why, 409)


# ── operations ───────────────────────────────────────────────────────────

def parse_detect(out):
    """i2cdetect -y grid -> (found, busy) lists of addresses."""
    found, busy = [], []
    for line in out.splitlines():
        m = re.match(r'^([0-7])0:', line)
        if not m:
            continue
        row = int(m.group(1)) * 16
        for col in range(16):
            cell = line[4 + col * 3: 6 + col * 3].strip().lower()
            if cell == 'uu':
                busy.append(row + col)
            elif re.fullmatch(r'[0-9a-f]{2}', cell):
                found.append(int(cell, 16))
    return found, busy


def scan(bus, mode='auto'):
    bus = check_bus(bus)
    if mode not in SCAN_MODES:
        raise I2CError('Bad scan mode')
    _guard()
    with _lock:
        out = _run(['i2cdetect', '-y', *SCAN_MODES[mode], str(bus)])
    found, busy = parse_detect(out)
    return {'bus': bus, 'mode': mode, 'found': found, 'busy': busy}


def read(bus, addr, reg=0, width=1, length=1, force=False):
    bus, addr = check_bus(bus), check_addr(addr)
    reg, width = check_reg(reg, width)
    length = _int(length, 'length', 1, MAX_LEN)
    _guard()
    args = ['i2ctransfer', '-y'] + (['-f'] if force else []) + [str(bus)]
    if width:
        args += [f'w{width}@{addr:#04x}'] + [f'{b:#04x}' for b in _reg_bytes(reg, width)] + [f'r{length}']
    else:
        args += [f'r{length}@{addr:#04x}']
    with _lock:
        out = _run(args)
    data = [int(t, 16) for t in out.split() if re.fullmatch(r'0x[0-9a-fA-F]{2}', t)]
    if len(data) != length:
        raise I2CError(f'Expected {length} byte(s), got {len(data)}')
    return {'bus': bus, 'addr': addr, 'reg': reg, 'width': width, 'data': data}


def write(bus, addr, data, reg=0, width=1, force=False):
    bus, addr = check_bus(bus), check_addr(addr)
    reg, width = check_reg(reg, width)
    data = parse_bytes(data)
    _guard()
    payload = _reg_bytes(reg, width) + data
    args = ['i2ctransfer', '-y'] + (['-f'] if force else []) + [str(bus), f'w{len(payload)}@{addr:#04x}'] + \
        [f'{b:#04x}' for b in payload]
    with _lock:
        _run(args)
    return {'bus': bus, 'addr': addr, 'reg': reg, 'width': width, 'written': len(data)}


# ── bus list + labels ────────────────────────────────────────────────────

def hint(addr):
    return next((text for (lo, hi), text in HINTS if lo <= addr <= hi), '')


def labels():
    """{"<bus>": {"0x41": "label"}} of this host (config ``i2c_labels``)."""
    raw = config.get('i2c_labels') or {}
    return raw if isinstance(raw, dict) else {}


def set_label(bus, addr, label):
    bus, addr = check_bus(bus), check_addr(addr)
    label = re.sub(r'\s+', ' ', str(label or '')).strip()[:80]
    all_labels = {k: dict(v) for k, v in labels().items() if isinstance(v, dict)}
    per_bus = all_labels.setdefault(str(bus), {})
    if label:
        per_bus[f'{addr:#04x}'] = label
    else:
        per_bus.pop(f'{addr:#04x}', None)
    if not per_bus:
        all_labels.pop(str(bus))
    config.save_key('i2c_labels', all_labels)
    return label


def buses():
    """Adapters with kernel clients (no scanning), saved labels and address hints."""
    lab = labels()
    out = []
    for b in udev.i2c_buses():
        if not b.get('node') and not _node_exists(b['bus']):
            continue
        out.append({'bus': b['bus'], 'name': b['name'], 'node': b['node'],
                    'clients': [{'addr': int(c['addr'], 16), 'name': c['name'], 'driver': c['driver']} for c in b['clients']],
                    'labels': dict(lab.get(str(b['bus'])) or {})})      # {"0x41": "label"}
    return {'buses': out, 'tools': tools_available(), 'hints': [[lo, hi, t] for (lo, hi), t in HINTS],
            'range': [ADDR_MIN, ADDR_MAX]}
