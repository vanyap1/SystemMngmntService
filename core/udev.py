"""udev and bus helpers for the Devices popup.

- ``device_list()``     device nodes from the udev database, grouped by kind
- ``usb_devices()``     USB topology like ``lsusb -t`` (+ hwdb names), ``pci_devices()``, ``i2c_buses()``
- rules files           list / read / save / delete in /etc/udev/rules.d, ``lint_rules()``
- ``monitor``           ``udevadm monitor`` running only while a client polls it (lease)
"""
import collections
import ctypes
import os
import signal
import re
import subprocess
import threading
import time

from core.shell import sh

SYS = '/sys'


def _read(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return default


def _driver(syspath):
    """Driver bound to the device (or its parent device) at ``syspath``."""
    for link in (os.path.join(syspath, 'driver'), os.path.join(syspath, 'device', 'driver')):
        if os.path.islink(link):
            return os.path.basename(os.readlink(link))
    return ''


# ── udev database ────────────────────────────────────────────────────────

def export_db():
    """Parse ``udevadm info --export-db`` into a list of records."""
    records = []
    for block in sh('udevadm info --export-db', timeout=10).split('\n\n'):
        rec = {'devpath': '', 'devnode': '', 'symlinks': [], 'props': {}}
        for line in block.split('\n'):
            key, _, value = line.partition(': ')
            if key == 'P':
                rec['devpath'] = value
            elif key == 'N':
                rec['devnode'] = '/dev/' + value
            elif key == 'S':
                rec['symlinks'].append('/dev/' + value)
            elif key == 'E':
                name, _, val = value.partition('=')
                rec['props'][name] = val
        if rec['devpath']:
            records.append(rec)
    return records


GROUPS = [
    ('serial',  'Serial ports',     'fa-solid fa-terminal'),
    ('usb',     'USB devices',      'fa-brands fa-usb'),
    ('video',   'Video / media',    'fa-solid fa-video'),
    ('i2c',     'I²C buses',        'fa-solid fa-microchip'),
    ('spi',     'SPI',              'fa-solid fa-microchip'),
    ('gpio',    'GPIO chips',       'fa-solid fa-plug'),
    ('block',   'Storage',          'fa-solid fa-hard-drive'),
    ('input',   'Input / HID',      'fa-solid fa-keyboard'),
    ('sound',   'Sound',            'fa-solid fa-volume-high'),
    ('net',     'Network',          'fa-solid fa-network-wired'),
    ('display', 'Display / GPU',    'fa-solid fa-display'),
    ('other',   'Other',            'fa-solid fa-cube'),
    ('virtual', 'Virtual / system', 'fa-solid fa-ghost'),
]
SERIAL_RE = re.compile(r'^tty(S|USB|ACM|AMA|FIQ|GS|XRUSB|THS|mxc)\d+$')


def _classify(sub, name, props):
    if sub == 'net':
        return 'net'
    if sub == 'block' and re.match(r'^(loop|ram)\d+$', name):
        return 'virtual'
    if sub == 'tty':
        return 'serial' if SERIAL_RE.match(name) else 'virtual'
    if sub == 'usb':
        return 'usb' if props.get('DEVTYPE') == 'usb_device' else None
    return {
        'video4linux': 'video', 'media': 'video',
        'i2c-dev': 'i2c', 'spidev': 'spi', 'gpio': 'gpio', 'block': 'block',
        'input': 'input', 'hidraw': 'input', 'sound': 'sound',
        'drm': 'display', 'graphics': 'display', 'cec': 'display',
        'mem': 'virtual', 'vc': 'virtual', 'vtconsole': 'virtual',
    }.get(sub, 'other')


def _size(sectors):
    try:
        b = int(sectors) * 512
    except ValueError:
        return ''
    for unit in ('B', 'K', 'M', 'G', 'T'):
        if b < 1024 or unit == 'T':
            return f"{b:.0f}{unit}" if unit == 'B' else f"{b:.1f}{unit}"
        b /= 1024


def _title(group, rec, syspath):
    """Human readable description of a device."""
    p = rec['props']
    usb = ' '.join(x for x in (p.get('ID_VENDOR_FROM_DATABASE') or p.get('ID_VENDOR', '').replace('_', ' '),
                               p.get('ID_MODEL_FROM_DATABASE') or p.get('ID_MODEL', '').replace('_', ' ')) if x)
    if group == 'usb':
        return usb
    if group == 'serial' and p.get('ID_BUS') == 'usb':
        return usb + (f" ({p['ID_SERIAL_SHORT']})" if p.get('ID_SERIAL_SHORT') else '')
    if group == 'video':
        return (p.get('ID_V4L_PRODUCT') or usb or _read(os.path.join(syspath, 'name'))
                or _read(os.path.join(syspath, 'model')))
    if group == 'input':
        return (_read(os.path.join(syspath, 'device', 'name')) or _read(os.path.join(syspath, 'name'))
                or usb)
    if group == 'block':
        parts = [p.get('ID_MODEL', '').replace('_', ' '), _size(_read(os.path.join(syspath, 'size'), '0'))]
        if p.get('ID_FS_TYPE'):
            parts.append(p['ID_FS_TYPE'] + (f" “{p['ID_FS_LABEL']}”" if p.get('ID_FS_LABEL') else ''))
        if p.get('DEVTYPE') == 'partition':
            parts.append('partition')
        return ' · '.join(x for x in parts if x)
    if group == 'net':
        parts = [_read(os.path.join(syspath, 'address')), _read(os.path.join(syspath, 'operstate'))]
        return ' · '.join(x for x in parts if x)
    if group == 'sound':
        return _read(os.path.join(syspath, 'device', 'id')) or usb
    return usb or _read(os.path.join(syspath, 'name')) or _read(os.path.join(syspath, 'device', 'name'))


def device_list():
    """Device nodes (and network interfaces) grouped by kind."""
    items = []
    for rec in export_db():
        p = rec['props']
        sub = p.get('SUBSYSTEM', '')
        node = rec['devnode'] or (p.get('INTERFACE', '') if sub == 'net' else '')
        if not node:
            continue
        name = os.path.basename(node)
        group = _classify(sub, name, p)
        if not group:
            continue
        syspath = SYS + rec['devpath']
        items.append({
            'group':     group,
            'node':      node,
            'name':      name if sub != 'usb' else f"{p.get('BUSNUM', '?')}:{p.get('DEVNUM', '?')}",
            'subsystem': sub,
            'devpath':   rec['devpath'],
            'title':     _title(group, rec, syspath),
            'driver':    p.get('ID_NET_DRIVER') or p.get('ID_USB_DRIVER') or _driver(syspath),
            'id':        (f"{p['ID_VENDOR_ID']}:{p['ID_MODEL_ID']}"
                          if p.get('ID_VENDOR_ID') and p.get('ID_MODEL_ID') else ''),
            'symlinks':  rec['symlinks'],
        })
    items.sort(key=lambda d: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', d['node'])])
    return {'groups': [{'key': k, 'label': l, 'icon': i} for k, l, i in GROUPS], 'devices': items}


# ── buses ────────────────────────────────────────────────────────────────

USB_CLASSES = {
    '00': 'Per interface', '01': 'Audio', '02': 'Communications', '03': 'HID', '05': 'Physical',
    '06': 'Image', '07': 'Printer', '08': 'Mass storage', '09': 'Hub', '0a': 'CDC data',
    '0b': 'Smart card', '0d': 'Content security', '0e': 'Video', '0f': 'Healthcare',
    '10': 'Audio/Video', '11': 'Billboard', 'dc': 'Diagnostic', 'e0': 'Wireless',
    'ef': 'Miscellaneous', 'fe': 'Application specific', 'ff': 'Vendor specific',
}


def usb_devices():
    """USB devices with their interfaces and device nodes; ``parent`` gives the topology."""
    db = export_db()
    devices, interfaces, nodes = {}, [], []
    for rec in db:
        p = rec['props']
        if p.get('SUBSYSTEM') == 'usb' and p.get('DEVTYPE') == 'usb_device':
            sp = SYS + rec['devpath']
            vendor_name = p.get('ID_VENDOR_FROM_DATABASE') or _read(sp + '/manufacturer')
            devices[rec['devpath']] = {
                'devpath':   rec['devpath'],
                'kernel':    os.path.basename(rec['devpath']),
                'bus':       int(_read(sp + '/busnum', '0') or 0),
                'dev':       int(_read(sp + '/devnum', '0') or 0),
                'vid':       _read(sp + '/idVendor'),
                'pid':       _read(sp + '/idProduct'),
                'vendor':    vendor_name,
                'product':   p.get('ID_MODEL_FROM_DATABASE') or _read(sp + '/product'),
                'manufacturer': _read(sp + '/manufacturer'),
                'product_str':  _read(sp + '/product'),
                'serial':    _read(sp + '/serial'),
                'speed':     _read(sp + '/speed'),
                'version':   _read(sp + '/version'),
                'class':     USB_CLASSES.get(_read(sp + '/bDeviceClass'), _read(sp + '/bDeviceClass')),
                'maxpower':  _read(sp + '/bMaxPower'),
                'driver':    p.get('DRIVER', ''),
                'parent':    None,
                'interfaces': [],
                'nodes':     [],
            }
        elif p.get('SUBSYSTEM') == 'usb' and p.get('DEVTYPE') == 'usb_interface':
            interfaces.append(rec)
        elif rec['devnode'] and not rec['devnode'].startswith('/dev/bus/usb/'):
            nodes.append(rec)

    def owner(devpath):
        """Deepest USB device that contains ``devpath``."""
        best = None
        for dp in devices:
            if devpath.startswith(dp + '/') and (best is None or len(dp) > len(best)):
                best = dp
        return best

    for dp, dev in devices.items():
        dev['parent'] = owner(dp)
    for rec in interfaces:
        dp = owner(rec['devpath'])
        if dp:
            cls = rec['props'].get('INTERFACE', '').split('/')[0]
            try:
                cls_name = USB_CLASSES.get(f"{int(cls):02x}", cls)
            except ValueError:
                cls_name = cls
            devices[dp]['interfaces'].append({
                'name':   os.path.basename(rec['devpath']),
                'class':  cls_name,
                'driver': rec['props'].get('DRIVER', '') or _driver(SYS + rec['devpath']),
            })
    for rec in nodes:
        dp = owner(rec['devpath'])
        if dp:
            devices[dp]['nodes'].append(rec['devnode'])
    for dev in devices.values():
        dev['interfaces'].sort(key=lambda i: i['name'])
        dev['nodes'].sort()
    return sorted(devices.values(), key=lambda d: (d['bus'], d['kernel']))


def pci_devices():
    """``lspci -vmmnnk`` parsed into dicts (empty if lspci is missing)."""
    out = []
    for block in sh('lspci -vmmnnk', timeout=10).split('\n\n'):
        dev = {}
        for line in block.split('\n'):
            key, _, value = line.partition(':\t')
            if value:
                dev[key.strip().lower()] = value.strip()
        if dev.get('slot'):
            out.append(dev)
    return out


def i2c_buses():
    """I²C adapters and the clients the kernel knows about (no bus scanning)."""
    base = SYS + '/bus/i2c/devices'
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    adapters = {}
    for n in names:
        m = re.match(r'^i2c-(\d+)$', n)
        if m:
            adapters[m.group(1)] = {'bus': int(m.group(1)), 'name': _read(f"{base}/{n}/name"),
                                    'node': f"/dev/{n}" if os.path.exists(f"/dev/{n}") else '',
                                    'clients': []}
    for n in names:
        m = re.match(r'^(\d+)-([0-9a-fA-F]{4})$', n)
        if m and m.group(1) in adapters:
            adapters[m.group(1)]['clients'].append({
                'addr':   '0x' + m.group(2)[2:].lower(),
                'name':   _read(f"{base}/{n}/name"),
                'driver': _driver(f"{base}/{n}"),
            })
    return sorted(adapters.values(), key=lambda a: a['bus'])


# ── rules files ──────────────────────────────────────────────────────────

RULES_DIRS = [  # (key, path, editable) in override order: /etc wins over /run over /lib
    ('local',   '/etc/udev/rules.d', True),
    ('runtime', '/run/udev/rules.d', False),
    ('system',  '/lib/udev/rules.d', False),
]
RULE_NAME = re.compile(r'^[\w.@+-]{1,100}\.rules$')
MAX_RULE_SIZE = 256 * 1024


class RuleError(Exception):
    pass


def rules_dir(key):
    for k, path, editable in RULES_DIRS:
        if k == key:
            return path, editable
    raise RuleError('Unknown rules directory')


def _rule_path(key, name):
    if not RULE_NAME.match(name or ''):
        raise RuleError('Rule file name must look like 99-name.rules')
    path, editable = rules_dir(key)
    return os.path.join(path, name), editable


def list_rules():
    files, seen = [], {}
    for key, path, editable in RULES_DIRS:
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if not e.name.endswith('.rules') or not e.is_file():
                continue
            st = e.stat()
            item = {'name': e.name, 'dir': key, 'path': e.path, 'editable': editable,
                    'size': st.st_size, 'mtime': int(st.st_mtime), 'overridden_by': seen.get(e.name)}
            seen.setdefault(e.name, key)
            files.append(item)
    files.sort(key=lambda f: (f['name'], [k for k, _, _ in RULES_DIRS].index(f['dir'])))
    return {'files': files, 'dirs': [{'key': k, 'path': p, 'editable': e} for k, p, e in RULES_DIRS]}


def read_rule(key, name):
    path, editable = _rule_path(key, name)
    try:
        with open(path) as f:
            return {'name': name, 'dir': key, 'path': path, 'editable': editable, 'text': f.read()}
    except FileNotFoundError:
        raise RuleError('File not found')
    except (OSError, UnicodeDecodeError) as e:
        raise RuleError(str(e))


def save_rule(name, text):
    path, _ = _rule_path('local', name)
    if len(text.encode()) > MAX_RULE_SIZE:
        raise RuleError('File is too large')
    if text and not text.endswith('\n'):
        text += '\n'
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w') as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise RuleError(f'Cannot write {path}: {e.strerror or e}')
    return path


def delete_rule(name):
    path, _ = _rule_path('local', name)
    try:
        os.unlink(path)
    except OSError as e:
        raise RuleError(f'Cannot delete {path}: {e.strerror or e}')
    return path


RULE_KEYS = {
    'ACTION', 'DEVPATH', 'KERNEL', 'KERNELS', 'NAME', 'SYMLINK', 'SUBSYSTEM', 'SUBSYSTEMS',
    'DRIVER', 'DRIVERS', 'ATTR', 'ATTRS', 'SYSCTL', 'ENV', 'CONST', 'TAG', 'TAGS', 'TEST',
    'PROGRAM', 'RESULT', 'OWNER', 'GROUP', 'MODE', 'SECLABEL', 'RUN', 'LABEL', 'GOTO',
    'IMPORT', 'OPTIONS',
}
_RULE_ITEM = re.compile(r'\s*([A-Z_]+)(\{[^}]*\})?\s*(==|!=|\+=|-=|:=|=)\s*"((?:[^"\\]|\\.)*)"\s*')


def lint_rules(text):
    """Light syntax check (udevadm verify needs systemd >= 254). Returns [{line, message}]."""
    problems, logical, start = [], '', 0
    lines = text.split('\n')
    for i, raw in enumerate(lines, 1):
        if not logical:
            start = i
        if raw.rstrip().endswith('\\'):
            logical += raw.rstrip()[:-1] + ' '
            continue
        logical += raw
        line, logical = logical.strip(), ''
        if not line or line.startswith('#'):
            continue
        pos = 0
        while pos < len(line):
            m = _RULE_ITEM.match(line, pos)
            if not m:
                problems.append({'line': start, 'message': f'Cannot parse near: {line[pos:pos + 40]}'})
                break
            key, attr, op = m.group(1), m.group(2), m.group(3)
            if key not in RULE_KEYS:
                problems.append({'line': start, 'message': f'Unknown key {key}'})
            elif key in ('ATTR', 'ATTRS', 'ENV', 'SYSCTL', 'SECLABEL', 'IMPORT') and attr is None:
                problems.append({'line': start, 'message': f'{key} needs {{attribute}}'})
            elif key in ('ACTION', 'DEVPATH', 'KERNELS', 'SUBSYSTEMS', 'DRIVERS', 'ATTRS', 'RESULT',
                         'CONST', 'TAGS') and op not in ('==', '!='):
                problems.append({'line': start, 'message': f'{key} only supports == and !='})
            pos = m.end()
            if pos < len(line):
                if line[pos] != ',':
                    problems.append({'line': start, 'message': f'Expected "," near: {line[pos:pos + 40]}'})
                    break
                pos += 1
    return problems


# ── event monitor ────────────────────────────────────────────────────────

def _die_with_parent():
    """preexec_fn: the child gets SIGTERM when the panel process exits (Linux prctl)."""
    try:
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


class UdevMonitor:
    """``udevadm monitor`` that runs only while somebody polls ``events()``."""
    LEASE_SECONDS = 10
    MAX_EVENTS = 1000
    HEADER = re.compile(r'^(KERNEL|UDEV)\s*\[([\d.]+)\]\s+(\S+)\s+(\S+)\s+\(([^)]*)\)')

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._events = collections.deque(maxlen=self.MAX_EVENTS)
        self._next_id = 1
        self._seen = 0.0
        self.error = None

    def _start(self):
        if self._proc and self._proc.poll() is None:
            return
        self.error = None
        try:
            self._proc = subprocess.Popen(
                ['stdbuf', '-oL', 'udevadm', 'monitor', '--kernel', '--udev', '--property'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, errors='replace', preexec_fn=_die_with_parent)
        except OSError as e:
            self._proc, self.error = None, str(e)
            return
        threading.Thread(target=self._read, args=(self._proc,), daemon=True, name='udev-monitor').start()
        threading.Thread(target=self._watch, daemon=True, name='udev-monitor-lease').start()

    def _stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None

    def _watch(self):
        while True:
            time.sleep(1)
            with self._lock:
                if not self._proc:
                    return
                if time.monotonic() - self._seen > self.LEASE_SECONDS:
                    self._stop()
                    return

    def _read(self, proc):
        event = None
        for line in proc.stdout:
            line = line.rstrip('\n')
            m = self.HEADER.match(line)
            if m:
                event = {'source': m.group(1).lower(), 'ts': float(m.group(2)), 'action': m.group(3),
                         'devpath': m.group(4), 'subsystem': m.group(5), 'time': time.time(), 'props': {}}
            elif event is not None and '=' in line:
                key, _, value = line.partition('=')
                event['props'][key] = value
            elif event is not None and not line:
                with self._lock:
                    event['id'] = self._next_id
                    self._next_id += 1
                    self._events.append(event)
                event = None
        with self._lock:
            if self._proc is proc and proc.poll() not in (None, 0, -15):
                self.error = f'udevadm monitor exited with code {proc.returncode}'

    def events(self, since=0):
        with self._lock:
            self._seen = time.monotonic()
            self._start()
            return {'events': [e for e in self._events if e['id'] > since],
                    'next': self._next_id - 1,
                    'running': bool(self._proc and self._proc.poll() is None),
                    'error': self.error}

    def clear(self):
        with self._lock:
            self._events.clear()


monitor = UdevMonitor()
