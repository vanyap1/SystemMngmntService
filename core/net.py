"""Network interfaces overview and a SocketCAN tool for the Devices popup.

- ``interfaces()``  ``ip -j -s -d addr`` + sysfs (driver, speed), CAN bit timing / bus state
- ``can_configure()`` / ``can_set_up()``  ``ip link set <can> ...`` (root)
- ``can_bus(iface)``  CAN_RAW socket: reader thread with a frame buffer, single and cyclic send.
  Like the GPIO control and the udev monitor it runs only while a client polls it (lease).
"""
import collections
import errno
import json
import os
import re
import socket
import struct
import threading
import time

from core.shell import quote, run_command, sh

IFACE_RE = re.compile(r'^[\w.-]{1,15}$')
ARPHRD_CAN = '280'
BITRATES = [10000, 20000, 50000, 100000, 125000, 250000, 500000, 800000, 1000000]

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x000007FF
CAN_ERR_MASK = 0x1FFFFFFF
SOL_CAN_RAW = 101
CAN_RAW_ERR_FILTER = 2
FRAME = struct.Struct('=IB3x8s')

ERR_CLASSES = [  # linux/can/error.h, class bits in can_id
    (0x001, 'TX timeout'), (0x002, 'lost arbitration'), (0x004, 'controller problem'),
    (0x008, 'protocol violation'), (0x010, 'transceiver problem'), (0x020, 'no ACK'),
    (0x040, 'bus off'), (0x080, 'bus error'), (0x100, 'controller restarted'),
]
ERR_CTRL = [  # data[1] for "controller problem"
    (0x01, 'RX overflow'), (0x02, 'TX overflow'), (0x04, 'RX warning'), (0x08, 'TX warning'),
    (0x10, 'RX passive'), (0x20, 'TX passive'), (0x40, 'back to error-active'),
]


class NetError(Exception):
    pass


def _read(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return default


def check_iface(name, can=False):
    if not IFACE_RE.match(str(name or '')) or not os.path.isdir(f'/sys/class/net/{name}'):
        raise NetError('Unknown network interface')
    if can and _read(f'/sys/class/net/{name}/type') != ARPHRD_CAN:
        raise NetError(f'{name} is not a CAN interface')
    return name


# ── interfaces ───────────────────────────────────────────────────────────

def _kind(link):
    info = (link.get('linkinfo') or {}).get('info_kind')
    if link.get('link_type') == 'loopback':
        return 'loopback'
    if link.get('link_type') == 'can':
        return info or 'can'
    if os.path.isdir(f"/sys/class/net/{link['ifname']}/wireless"):
        return 'wlan'
    return info or link.get('link_type', '')


def interfaces():
    try:
        links = json.loads(sh('ip -j -s -d addr show', timeout=5) or '[]')
    except ValueError:
        links = []
    out = []
    for link in links:
        name = link['ifname']
        sysdir = f'/sys/class/net/{name}'
        driver_link = os.path.join(sysdir, 'device', 'driver')
        stats = link.get('stats64') or {}
        item = {
            'name':     name,
            'kind':     _kind(link),
            'up':       'UP' in link.get('flags', []),
            'carrier':  'LOWER_UP' in link.get('flags', []),
            'operstate': link.get('operstate', ''),
            'flags':    link.get('flags', []),
            'mac':      link.get('address', '') if link.get('link_type') == 'ether' else '',
            'mtu':      link.get('mtu'),
            'driver':   os.path.basename(os.readlink(driver_link)) if os.path.islink(driver_link) else '',
            'parent':   link.get('parentdev', ''),
            'speed':    _read(sysdir + '/speed') if link.get('operstate') == 'UP' else '',
            'addrs':    [{'family': a.get('family'), 'addr': f"{a.get('local')}/{a.get('prefixlen')}",
                          'scope': a.get('scope', '')} for a in link.get('addr_info', [])],
            'rx':       stats.get('rx', {}),
            'tx':       stats.get('tx', {}),
            'time':     time.time(),
        }
        data = (link.get('linkinfo') or {}).get('info_data') or {}
        if link.get('link_type') == 'can':
            bt = data.get('bittiming') or {}
            item['can'] = {
                'state':        data.get('state', ''),
                'bitrate':      bt.get('bitrate'),
                'sample_point': bt.get('sample_point'),
                'restart_ms':   data.get('restart_ms'),
                'ctrlmode':     data.get('ctrlmode', []),
                'clock':        data.get('clock'),
                'berr':         data.get('berr_counter') or {},
                'configurable': item['kind'] == 'can',
            }
        out.append(item)
    return out


def routes():
    try:
        r4 = json.loads(sh('ip -j route show', timeout=5) or '[]')
    except ValueError:
        r4 = []
    dns = [line.split()[1] for line in _read('/etc/resolv.conf').split('\n')
           if line.startswith('nameserver') and len(line.split()) > 1]
    return {'routes': [{'dst': r.get('dst'), 'gateway': r.get('gateway', ''), 'dev': r.get('dev', ''),
                        'proto': r.get('protocol', ''), 'src': r.get('prefsrc', ''), 'metric': r.get('metric', '')}
                       for r in r4],
            'dns': dns}


# ── CAN link configuration (root) ────────────────────────────────────────

def _ip(args):
    out = run_command(f'sudo ip link set {args}', timeout=10)
    if out.startswith('Error!'):
        raise NetError(out.replace('Error!\n', '').strip())


def can_set_up(iface, up):
    check_iface(iface, can=True)
    _ip(f"{quote(iface)} {'up' if up else 'down'}")


def can_configure(iface, bitrate, sample_point=None, restart_ms=None, listen_only=False):
    """Bring the interface down, apply bit timing, bring it up again."""
    check_iface(iface, can=True)
    try:
        bitrate = int(bitrate)
    except (TypeError, ValueError):
        raise NetError('Bitrate must be a number')
    if not 1000 <= bitrate <= 1000000:
        raise NetError('Bitrate must be 1000…1000000')
    args = [f'type can bitrate {bitrate}']
    if sample_point not in (None, ''):
        try:
            sp = float(sample_point)
        except ValueError:
            raise NetError('Sample point must be a number like 0.875')
        if not 0.5 <= sp < 1:
            raise NetError('Sample point must be 0.5…0.999')
        args.append(f'sample-point {sp:.3f}')
    if restart_ms not in (None, ''):
        try:
            args.append(f'restart-ms {max(0, int(restart_ms))}')
        except ValueError:
            raise NetError('restart-ms must be a number')
    args.append('listen-only ' + ('on' if listen_only else 'off'))
    _ip(f'{quote(iface)} down')
    _ip(f"{quote(iface)} {' '.join(args)}")
    _ip(f'{quote(iface)} up')


# ── CAN raw socket ───────────────────────────────────────────────────────

def parse_frame(can_id, ext=False, rtr=False, data=''):
    """Validate user input -> (raw can_id, dlc, payload bytes)."""
    try:
        cid = int(str(can_id).strip().lower().removeprefix('0x'), 16)
    except ValueError:
        raise NetError('ID must be hexadecimal, e.g. 123 or 18FF50E5')
    ext = bool(ext) or cid > CAN_SFF_MASK
    if cid > (CAN_EFF_MASK if ext else CAN_SFF_MASK):
        raise NetError('ID is out of range')
    text = re.sub(r'[\s,:;-]', '', str(data or '')).removeprefix('0x')
    if len(text) % 2 or not re.fullmatch(r'[0-9a-fA-F]*', text):
        raise NetError('Data must be hex bytes, e.g. "11 22 33"')
    payload = bytes.fromhex(text)
    if len(payload) > 8:
        raise NetError('Classic CAN carries at most 8 data bytes')
    raw = cid | (CAN_EFF_FLAG if ext else 0) | (CAN_RTR_FLAG if rtr else 0)
    dlc = len(payload)
    if rtr:
        payload = b''
    return raw, dlc, payload


def _describe_error(can_id, data):
    parts = [name for bit, name in ERR_CLASSES if can_id & bit]
    if can_id & 0x004 and len(data) > 1:
        parts += [name for bit, name in ERR_CTRL if data[1] & bit]
    return ', '.join(parts) or 'error frame'


class CanBus:
    LEASE_SECONDS = 10
    MAX_FRAMES = 2000
    MIN_PERIOD_MS = 5

    def __init__(self, iface):
        self.iface = iface
        self._lock = threading.Lock()
        self._sock = None
        self._frames = collections.deque(maxlen=self.MAX_FRAMES)
        self._next_id = 1
        self._seen = 0.0
        self._jobs = {}             # job id -> dict (+ '_stop' Event)
        self._job_seq = 0
        self.error = None

    # lifecycle

    def _open(self):
        if self._sock:
            return
        try:
            s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            s.setsockopt(SOL_CAN_RAW, CAN_RAW_ERR_FILTER, struct.pack('=I', CAN_ERR_MASK))
            s.bind((self.iface,))
            s.settimeout(0.5)
        except OSError as e:
            self.error = f'Cannot open {self.iface}: {e.strerror or e}'
            return
        self._sock, self.error = s, None
        threading.Thread(target=self._read, args=(s,), daemon=True, name=f'can-{self.iface}').start()
        threading.Thread(target=self._watch, args=(s,), daemon=True, name=f'can-{self.iface}-lease').start()

    def _close(self):
        for job in self._jobs.values():
            job['_stop'].set()
        self._jobs.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _watch(self, sock):
        while True:
            time.sleep(1)
            with self._lock:
                if self._sock is not sock:
                    return
                if time.monotonic() - self._seen > self.LEASE_SECONDS:
                    self._close()
                    return

    def _record(self, direction, can_id, dlc, data, error=''):
        frame = {'id': self._next_id, 't': time.time(), 'dir': direction,
                 'can_id': can_id & (CAN_EFF_MASK if can_id & CAN_EFF_FLAG else CAN_SFF_MASK),
                 'ext': bool(can_id & CAN_EFF_FLAG), 'rtr': bool(can_id & CAN_RTR_FLAG),
                 'dlc': dlc, 'data': data.hex(), 'error': error}
        self._next_id += 1
        self._frames.append(frame)

    def _read(self, sock):
        while True:
            try:
                raw = sock.recv(FRAME.size)
            except socket.timeout:
                if self._sock is not sock:
                    return
                continue
            except OSError as e:
                with self._lock:
                    if self._sock is sock:
                        if e.errno == errno.ENETDOWN:
                            time.sleep(0.5)     # interface is down: keep waiting for it
                            continue
                        self.error = f'Receive error: {e.strerror or e}'
                        self._close()
                return
            if len(raw) < FRAME.size:
                continue
            can_id, dlc, data = FRAME.unpack(raw)
            dlc = min(dlc, 8)
            with self._lock:
                if can_id & CAN_ERR_FLAG:
                    self._record('err', can_id & CAN_ERR_MASK, dlc, data[:dlc],
                                 _describe_error(can_id & CAN_ERR_MASK, data[:dlc]))
                else:
                    self._record('rx', can_id, dlc, data[:0] if can_id & CAN_RTR_FLAG else data[:dlc])

    # API (all calls keep the lease alive)

    def touch(self):
        self._seen = time.monotonic()
        self._open()

    def frames(self, since=0):
        with self._lock:
            self.touch()
            return {'frames': [f for f in self._frames if f['id'] > since],
                    'next': self._next_id - 1,
                    'running': self._sock is not None,
                    'error': self.error,
                    'jobs': [{k: v for k, v in j.items() if not k.startswith('_')} for j in self._jobs.values()]}

    def _send_raw(self, raw, dlc, payload):
        sock = self._sock
        if not sock:
            raise NetError(self.error or 'CAN socket is not open')
        try:
            sock.send(FRAME.pack(raw, dlc, payload.ljust(8, b'\0')))
        except OSError as e:
            hint = ' (interface is down — press Open)' if e.errno == errno.ENETDOWN else \
                   ' (TX queue full: no ACK on the bus?)' if e.errno == errno.ENOBUFS else ''
            raise NetError(f'Send failed: {e.strerror or e}{hint}')
        with self._lock:
            self._record('tx', raw, dlc, payload)

    def send(self, can_id, ext=False, rtr=False, data=''):
        frame = parse_frame(can_id, ext, rtr, data)
        with self._lock:
            self.touch()
        self._send_raw(*frame)

    def start_cyclic(self, can_id, ext, rtr, data, period_ms):
        frame = parse_frame(can_id, ext, rtr, data)
        try:
            period = max(self.MIN_PERIOD_MS, int(period_ms))
        except (TypeError, ValueError):
            raise NetError('Period must be a number of milliseconds')
        with self._lock:
            self.touch()
            if not self._sock:
                raise NetError(self.error or 'CAN socket is not open')
            self._job_seq += 1
            raw, dlc, payload = frame
            job = {'job': self._job_seq, 'can_id': raw & (CAN_EFF_MASK if raw & CAN_EFF_FLAG else CAN_SFF_MASK),
                   'ext': bool(raw & CAN_EFF_FLAG), 'rtr': bool(raw & CAN_RTR_FLAG), 'data': payload.hex(),
                   'period_ms': period, 'sent': 0, 'errors': 0, 'last_error': '', '_stop': threading.Event()}
            self._jobs[job['job']] = job
        threading.Thread(target=self._cyclic, args=(job, frame), daemon=True,
                         name=f"can-{self.iface}-cyclic-{job['job']}").start()
        return job['job']

    def _cyclic(self, job, frame):
        period = job['period_ms'] / 1000
        next_at = time.monotonic()
        while not job['_stop'].is_set():
            try:
                self._send_raw(*frame)
                job['sent'] += 1
            except NetError as e:
                job['errors'] += 1
                job['last_error'] = str(e)
            next_at += period
            delay = next_at - time.monotonic()
            if delay < 0:               # fell behind: do not burst to catch up
                next_at, delay = time.monotonic(), 0
            job['_stop'].wait(delay)

    def stop_cyclic(self, job_id=None):
        with self._lock:
            self.touch()
            for jid in ([job_id] if job_id is not None else list(self._jobs)):
                job = self._jobs.pop(jid, None)
                if job:
                    job['_stop'].set()

    def clear(self):
        with self._lock:
            self._frames.clear()


_buses = {}
_buses_lock = threading.Lock()


def can_bus(iface):
    check_iface(iface, can=True)
    with _buses_lock:
        if iface not in _buses:
            _buses[iface] = CanBus(iface)
        return _buses[iface]


def stop_all_cyclic():
    """Stop every cyclic CAN transmission (e.g. before a test script starts)."""
    with _buses_lock:
        buses = list(_buses.values())
    for bus in buses:
        bus.stop_cyclic()
