"""Network interfaces overview and a SocketCAN tool for the Devices popup.

- ``interfaces()``  ``ip -j -s -d addr`` + sysfs (driver, speed), CAN bit timing / bus state
- ``can_configure()`` / ``can_set_up()``  ``ip link set <can> ...`` (root)
- ``can_bus(iface)``  CAN_RAW socket: reader thread with a frame buffer, per-ID statistics
  (count, cycle time — exact even when the buffer overflows), single and cyclic send, recording to a
  trace file and a trace player (into the view or onto the bus) — files: ``core/can_trace.py``.
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

from core import can_trace
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
SO_TIMESTAMP = getattr(socket, 'SO_TIMESTAMP', 29)

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

CHECKSUMS = ('toyota', 'sum8', 'xor8')
COUNTER_BITS = {'0-7': (0, 8), '0-3': (0, 4), '4-7': (4, 4), '0-1': (0, 2)}


def check_mods(cs=None, cnt=None):
    """Per-frame modifiers of a TX row: checksum type ('' / toyota / sum8 / xor8) in the last byte and a rolling
    counter {byte, bits: '0-7' | '0-3' | '4-7' | '0-1'} -> (cs, (byte, shift, width) or None)."""
    cs = cs or ''
    if cs not in ('',) + CHECKSUMS:
        raise NetError(f'Unknown checksum: {cs}')
    if not cnt:
        return cs, None
    if not isinstance(cnt, dict):
        raise NetError('Bad counter')
    try:
        byte = int(cnt.get('byte'))
    except (TypeError, ValueError):
        raise NetError('Counter byte must be 0…7')
    if not 0 <= byte <= 7 or cnt.get('bits', '0-7') not in COUNTER_BITS:
        raise NetError('Counter: byte 0…7, bits 0-7 / 0-3 / 4-7 / 0-1')
    return cs, (byte,) + COUNTER_BITS[cnt.get('bits', '0-7')]


def checksum(kind, raw_id, dlc, data):
    """Checksum byte over data[0 .. dlc-2]. toyota = (ID bytes + DLC + data) & 0xFF (for 0x0B4, DLC 8:
    0xB4 + 0x00 + 0x08 + D0 … D6); sum8 = data sum & 0xFF; xor8 = data XOR."""
    body = data[:max(0, dlc - 1)]
    if kind == 'xor8':
        v = 0
        for b in body:
            v ^= b
        return v
    v = sum(body)
    if kind == 'toyota':
        cid = raw_id & (CAN_EFF_MASK if raw_id & CAN_EFF_FLAG else CAN_SFF_MASK)
        v += sum((cid >> (8 * k)) & 0xFF for k in range(4)) + dlc
    return v & 0xFF


def apply_mods(raw_id, dlc, payload, cs, cnt, n=0):
    """The payload of one transmission: the counter field advanced by ``n`` (from its value in the data), then the
    checksum into the last byte — both change together in every frame."""
    if raw_id & CAN_RTR_FLAG or (not cs and not cnt) or not dlc:
        return payload
    p = bytearray(payload.ljust(dlc, b'\0')[:dlc])
    if cnt and cnt[0] < dlc:
        byte, shift, width = cnt
        mask = (1 << width) - 1
        v = (((p[byte] >> shift) & mask) + n) & mask
        p[byte] = (p[byte] & ~(mask << shift) & 0xFF) | (v << shift)
    if cs:
        p[dlc - 1] = checksum(cs, raw_id, dlc, p)
    return bytes(p)


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
    MAX_IDS = 2048              # per-ID statistics entries (new IDs beyond it are only counted)
    CYCLE_ALPHA = 0.2           # smoothing of the average cycle time
    MIN_PERIOD_MS = 5
    MAX_REC_BYTES = 1 << 30     # a recording stops at 1 GiB
    SPEEDS = (0.1, 0.25, 0.5, 1, 2, 4, 10)
    PLAY_MAX_ERRORS = 100       # consecutive send errors that stop a replay onto the bus
    WATCH_MAX = 20000           # frames of the analysed ID kept for the analyser
    WATCH_LEASE = 5             # seconds without a watch poll that end the watch

    def __init__(self, iface):
        self.iface = iface
        self._lock = threading.Lock()
        self._sock = None
        self._frames = collections.deque(maxlen=self.MAX_FRAMES)
        self._next_id = 1
        self._ids = {}              # key -> statistics of one ID (see _count)
        self._totals = {'rx': 0, 'tx': 0, 'err': 0, 'rp': 0, 'dropped_ids': 0}
        self._rec = None            # recording: {path, frames, bytes, started, _f}
        self._rec_last = None       # how the last recording ended (shown once in the UI)
        self._play = None           # player: see play_start
        self._play_last = None
        self._watch_key = None      # analyser: every frame of one ID (can_trace.frame_key) into its own buffer
        self._watch_frames = collections.deque(maxlen=self.WATCH_MAX)
        self._watch_seen = 0.0
        self._seen = 0.0
        self._jobs = {}             # job id -> dict (+ '_stop' Event)
        self._job_seq = 0
        self.error = None

    # lifecycle

    def _open(self):
        if self._sock:
            return
        s = None
        try:
            s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            s.setsockopt(SOL_CAN_RAW, CAN_RAW_ERR_FILTER, struct.pack('=I', CAN_ERR_MASK))
            try:
                s.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMP, 1)   # kernel receive time: exact cycle times
            except OSError:
                pass
            s.bind((self.iface,))
            s.settimeout(0.5)
        except OSError as e:
            if s:
                s.close()
            self.error = f'Cannot open {self.iface}: {e.strerror or e}'
            return
        self._sock, self.error = s, None
        threading.Thread(target=self._read, args=(s,), daemon=True, name=f'can-{self.iface}').start()
        threading.Thread(target=self._watch, args=(s,), daemon=True, name=f'can-{self.iface}-lease').start()

    def _close(self):
        self._stop_rec()
        if self._play:
            self._play['_stop'].set()
        for job in self._jobs.values():
            job['_stop'].set()
            job['_wake'].set()
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
                if self._watch_key and time.monotonic() - self._watch_seen > self.WATCH_LEASE:
                    self._watch_key = None
                    self._watch_frames.clear()
                if self._rec:
                    try:
                        self._rec['_f'].flush()
                    except OSError as e:
                        self._stop_rec(f'Write error: {e.strerror or e}')

    def _record(self, direction, can_id, dlc, data, error='', t=None):
        frame = {'id': self._next_id, 't': t or time.time(), 'dir': direction,
                 'can_id': can_id & (CAN_EFF_MASK if can_id & CAN_EFF_FLAG else CAN_SFF_MASK),
                 'ext': bool(can_id & CAN_EFF_FLAG), 'rtr': bool(can_id & CAN_RTR_FLAG),
                 'dlc': dlc, 'data': data.hex(), 'error': error}
        self._next_id += 1
        self._frames.append(frame)
        self._count(frame)
        if self._watch_key and _key(frame) == self._watch_key:
            self._watch_frames.append(frame)
        if self._rec and direction != 'rp':
            self._write_rec(frame)

    def _count(self, f):
        """Per-ID statistics like PCAN-View's receive / transmit list (caller holds the lock)."""
        self._totals[f['dir']] += 1
        key = f"{f['dir']}:{'x' if f['ext'] else 's'}:{f['can_id']:x}" + (':' + f['error'] if f['error'] else '')
        row = self._ids.get(key)
        if row is None:
            if len(self._ids) >= self.MAX_IDS:
                self._totals['dropped_ids'] += 1
                return
            self._ids[key] = {'key': key, 'dir': f['dir'], 'can_id': f['can_id'], 'ext': f['ext'], 'rtr': f['rtr'],
                              'dlc': f['dlc'], 'data': f['data'], 'error': f['error'], 'count': 1,
                              'first': f['t'], 't': f['t'], 'n': f['id'],
                              'period': None, 'avg': None, 'min': None, 'max': None}
            return
        dt = max(0.0, f['t'] - row['t'])
        row['period'] = dt
        row['avg'] = dt if row['avg'] is None else row['avg'] + self.CYCLE_ALPHA * (dt - row['avg'])
        row['min'] = dt if row['min'] is None else min(row['min'], dt)
        row['max'] = dt if row['max'] is None else max(row['max'], dt)
        row.update(rtr=f['rtr'], dlc=f['dlc'], data=f['data'], t=f['t'], n=f['id'])
        row['count'] += 1

    @staticmethod
    def _stamp(ancdata):
        """Kernel receive time from an SCM_TIMESTAMP message (struct timeval, 32- or 64-bit longs)."""
        for level, kind, data in ancdata:
            if level == socket.SOL_SOCKET and kind == SO_TIMESTAMP:
                if len(data) >= 16:
                    sec, usec = struct.unpack('=qq', data[:16])
                elif len(data) >= 8:
                    sec, usec = struct.unpack('=ii', data[:8])
                else:
                    continue
                return sec + usec / 1e6
        return None

    def _read(self, sock):
        while True:
            try:
                raw, ancdata, _flags, _addr = sock.recvmsg(FRAME.size, socket.CMSG_SPACE(16))
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
            t = self._stamp(ancdata)
            with self._lock:
                if can_id & CAN_ERR_FLAG:
                    self._record('err', can_id & CAN_ERR_MASK, dlc, data[:dlc],
                                 _describe_error(can_id & CAN_ERR_MASK, data[:dlc]), t)
                else:
                    self._record('rx', can_id, dlc, data[:0] if can_id & CAN_RTR_FLAG else data[:dlc], t=t)

    # API (all calls keep the lease alive)

    def touch(self):
        self._seen = time.monotonic()
        self._open()

    def frames(self, since=0):
        """Frames and per-ID rows changed after frame ``since`` (0 = all), totals since Clear."""
        with self._lock:
            self.touch()
            return {'frames': [f for f in self._frames if f['id'] > since],
                    'ids': [dict(r) for r in self._ids.values() if r['n'] > since],
                    'totals': dict(self._totals),
                    'now': time.time(),
                    'next': self._next_id - 1,
                    'running': self._sock is not None,
                    'error': self.error,
                    'jobs': [_public(j) for j in self._jobs.values()],
                    'rec': _public(self._rec) if self._rec else None, 'rec_last': self._rec_last,
                    'play': _public(self._play) if self._play else None, 'play_last': self._play_last,
                    'speeds': self.SPEEDS}

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

    def send(self, can_id, ext=False, rtr=False, data='', cs=None, cnt=None):
        raw, dlc, payload = parse_frame(can_id, ext, rtr, data)
        cs, cnt = check_mods(cs, cnt)
        with self._lock:
            self.touch()
        self._send_raw(raw, dlc, apply_mods(raw, dlc, payload, cs, cnt))

    def _period(self, period_ms):
        try:
            return max(self.MIN_PERIOD_MS, min(3600000, int(period_ms)))
        except (TypeError, ValueError):
            raise NetError('Period must be a number of milliseconds')

    @staticmethod
    def _job_frame(job, frame, mods=None):
        raw, dlc, payload = frame
        if mods is not None:
            job['_mods'] = mods
            job['cs'], job['cnt'] = mods[0], bool(mods[1])
        job.update(can_id=raw & (CAN_EFF_MASK if raw & CAN_EFF_FLAG else CAN_SFF_MASK), ext=bool(raw & CAN_EFF_FLAG),
                   rtr=bool(raw & CAN_RTR_FLAG), dlc=dlc, data=payload.hex(), _frame=frame)

    def start_cyclic(self, can_id, ext, rtr, data, period_ms, tag='', cs=None, cnt=None):
        """Send a frame every ``period_ms``. ``tag`` names the job for its client (a TX list row): starting a tag that
        runs replaces its frame and period (like ``update_cyclic``)."""
        frame = parse_frame(can_id, ext, rtr, data)
        mods = check_mods(cs, cnt)
        period = self._period(period_ms)
        tag = str(tag or '')[:40]
        with self._lock:
            self.touch()
            if not self._sock:
                raise NetError(self.error or 'CAN socket is not open')
            if tag:
                for job in self._jobs.values():
                    if job['tag'] == tag:
                        self._job_frame(job, frame, mods)
                        job['period_ms'] = period
                        return job['job']
            self._job_seq += 1
            job = {'job': self._job_seq, 'tag': tag, 'period_ms': period, 'sent': 0, 'errors': 0, 'last_error': '',
                   'updated': 0, '_stop': threading.Event(), '_wake': threading.Event()}
            self._job_frame(job, frame, mods)
            self._jobs[job['job']] = job
        threading.Thread(target=self._cyclic, args=(job,), daemon=True,
                         name=f"can-{self.iface}-cyclic-{job['job']}").start()
        return job['job']

    def update_cyclic(self, job_id, can_id=None, ext=False, rtr=False, data=None, period_ms=None, cs=None, cnt=None):
        """Change a running cyclic job on the fly: the next transmission carries the new frame; a new period
        applies from the next cycle (a shorter one at once)."""
        frame = parse_frame(can_id, ext, rtr, data) if can_id is not None else None
        mods = check_mods(cs, cnt) if frame else None
        period = self._period(period_ms) if period_ms is not None else None
        with self._lock:
            self.touch()
            job = self._jobs.get(job_id)
            if not job:
                raise NetError('This transmission is not running')
            if frame:
                self._job_frame(job, frame, mods)
            if period and period != job['period_ms']:
                job['period_ms'] = period
                job['_wake'].set()
            job['updated'] += 1

    def _cyclic(self, job):
        planned = time.monotonic()          # when this transmission was due (keeps the period without drift)
        n = 0       # rolling counter: frames sent by this job — keeps running when the data is edited on the fly
        while not job['_stop'].is_set():
            raw, dlc, payload = job['_frame']
            cs, cnt = job.get('_mods') or ('', None)
            try:
                self._send_raw(raw, dlc, apply_mods(raw, dlc, payload, cs, cnt, n))
                n += 1
                job['sent'] += 1
            except NetError as e:
                job['errors'] += 1
                job['last_error'] = str(e)
            while not job['_stop'].is_set():
                job['_wake'].clear()
                due = planned + job['period_ms'] / 1000      # re-read: the period may change while waiting
                delay = due - time.monotonic()
                if delay <= 0:
                    # fell behind: do not burst to catch up
                    planned = due if delay > -job['period_ms'] / 1000 else time.monotonic()
                    break
                job['_wake'].wait(delay)

    def stop_cyclic(self, job_id=None):
        with self._lock:
            self.touch()
            for jid in ([job_id] if job_id is not None else list(self._jobs)):
                job = self._jobs.pop(jid, None)
                if job:
                    job['_stop'].set()
                    job['_wake'].set()

    # recording (caller of the _ helpers holds the lock)

    def _write_rec(self, frame):
        rec = self._rec
        line = can_trace.format_line(frame, self.iface)
        try:
            rec['_f'].write(line)
        except OSError as e:
            self._stop_rec(f'Write error: {e.strerror or e}')
            return
        rec['frames'] += 1
        rec['bytes'] += len(line)
        if rec['bytes'] >= self.MAX_REC_BYTES:
            self._stop_rec('Size limit reached (1 GiB)')

    def _stop_rec(self, error=''):
        rec = self._rec
        if not rec:
            return
        self._rec = None
        try:
            rec['_f'].close()
        except OSError as e:
            error = error or f'Write error: {e.strerror or e}'
        self._rec_last = dict(_public(rec), error=error, stopped=time.time())

    def record_start(self, rel, append=False):
        """Write every rx / tx / error frame to the trace ``rel`` (new file, or ``append`` to an existing one)."""
        path, rel = can_trace.check_path(rel)
        with self._lock:
            self.touch()
            if not self._sock:
                raise NetError(self.error or 'CAN socket is not open')
            if self._rec:
                raise NetError(f"Already recording to {self._rec['path']}")
            if self._play and self._play['path'] == rel:
                raise NetError('This file is being played')
            exists = os.path.exists(path)
            if append and not exists:
                raise NetError(f'"{rel}" not found')
            if not append and exists:
                raise NetError(f'"{rel}" already exists — choose it to append')
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                f = open(path, 'a' if append else 'x', encoding='utf-8')
                size = f.tell()
                head = f"# recording {time.strftime('%Y-%m-%d %H:%M:%S')} on {self.iface}\n"
                f.write(head)
            except OSError as e:
                raise NetError(f'Cannot write {rel}: {e.strerror or e}')
            self._rec = {'path': rel, 'append': bool(append), 'frames': 0, 'bytes': size + len(head),
                         'started': time.time(), '_f': f}
            self._rec_last = None
            return rel

    def record_stop(self):
        with self._lock:
            self.touch()
            self._stop_rec()

    # player

    def play_start(self, rel, mode='view', speed=1, loop=False, skip=None):
        """Replay a trace with its timing: ``mode`` view = frames into the list as ``rp`` (nothing is sent),
        bus = rx / tx frames sent onto the bus (error frames are skipped). ``skip`` = ID keys
        (``can_trace.frame_key``) left out — their time still passes."""
        path, rel = can_trace.existing_file(rel)
        skip = can_trace.check_keys(skip)
        if mode not in ('view', 'bus'):
            raise NetError('Mode must be view or bus')
        with self._lock:
            self.touch()
            if not self._sock:
                raise NetError(self.error or 'CAN socket is not open')
            if self._play:
                raise NetError(f"Already playing {self._play['path']}")
            if self._rec and self._rec['path'] == rel:
                raise NetError('This file is being recorded')
            p = {'path': rel, 'mode': mode, 'speed': _speed(speed), 'loop': bool(loop), 'paused': False,
                 'frames': 0, 'errors': 0, 'error': '', 'loops': 0, 'pos': 0, 'size': os.path.getsize(path),
                 'elapsed': 0.0, 'started': time.time(), 'skip': sorted(skip), 'skipped': 0,
                 '_skip': skip, '_stop': threading.Event()}
            self._play, self._play_last = p, None
        threading.Thread(target=self._player, args=(p, path), daemon=True, name=f'can-{self.iface}-play').start()
        return rel

    def play_control(self, action, speed=None, loop=None, skip=None):
        skip = can_trace.check_keys(skip) if skip is not None else None
        with self._lock:
            self.touch()
            p = self._play
            if not p:
                raise NetError('Nothing is playing')
            if action == 'pause':
                p['paused'] = True
            elif action == 'resume':
                p['paused'] = False
            elif action == 'stop':
                p['_stop'].set()
            elif action == 'set':
                if speed is not None:
                    p['speed'] = _speed(speed)
                if loop is not None:
                    p['loop'] = bool(loop)
                if skip is not None:
                    p['_skip'], p['skip'] = skip, sorted(skip)
            else:
                raise NetError('Unknown player action')

    def _player(self, p, path):
        stop = p['_stop']
        clock = {'v': 0.0, 'tick': time.monotonic()}   # trace seconds played, advanced by real time × speed
        fails = 0
        try:
            while not stop.is_set():
                target = clock['v']
                prev = None
                with open(path, 'rb') as f:
                    for raw in f:
                        if stop.is_set():
                            break
                        p['pos'] = f.tell()
                        if raw.startswith(b'#'):
                            prev = None             # next recording session: no pause across the gap
                            continue
                        fr = can_trace.parse_line(raw.decode('utf-8', 'replace'))
                        if not fr:
                            continue
                        if prev is not None and fr['t'] > prev:
                            target += fr['t'] - prev
                        prev = fr['t']
                        self._play_wait(p, clock, target)
                        if stop.is_set():
                            break
                        fails = 0 if self._play_emit(p, fr) else fails + 1
                        if fails >= self.PLAY_MAX_ERRORS:
                            p['error'] = f"Stopped after {fails} send errors: {p['error']}"
                            stop.set()
                if stop.is_set() or not p['loop']:
                    break
                p['loops'] += 1
        except OSError as e:
            p['error'] = f'Read error: {e.strerror or e}'
        finally:
            with self._lock:
                if self._play is p:
                    self._play = None
                self._play_last = dict(_public(p), stopped=time.time(), done=not stop.is_set())

    @staticmethod
    def _play_wait(p, clock, target):
        while not p['_stop'].is_set():
            now = time.monotonic()
            if not p['paused']:
                clock['v'] += (now - clock['tick']) * p['speed']
            clock['tick'] = now
            p['elapsed'] = clock['v']
            if clock['v'] >= target:
                return
            p['_stop'].wait(0.1 if p['paused'] else min(0.05, (target - clock['v']) / p['speed']))

    def _play_emit(self, p, fr):
        """One replayed frame; False when sending it failed."""
        if p['_skip'] and can_trace.frame_key(fr) in p['_skip']:
            p['skipped'] += 1
            return True
        payload = bytes.fromhex(fr['data'])
        raw = fr['can_id'] | (CAN_EFF_FLAG if fr['ext'] else 0) | (CAN_RTR_FLAG if fr['rtr'] else 0)
        if p['mode'] == 'view':
            with self._lock:
                self._record('rp', raw, fr['dlc'], payload,
                             _describe_error(fr['can_id'], payload) if fr['dir'] == 'err' else '')
            p['frames'] += 1
            return True
        if fr['dir'] == 'err':
            return True
        try:
            self._send_raw(raw, fr['dlc'], payload)
        except NetError as e:
            p['errors'] += 1
            p['error'] = str(e)
            return False
        p['frames'] += 1
        return True

    def stop_tx(self):
        """Stop everything that transmits: cyclic jobs and a replay onto the bus."""
        self.stop_cyclic()
        with self._lock:
            if self._play and self._play['mode'] == 'bus':
                self._play['_stop'].set()

    # analyser: one ID, every frame

    def watch(self, key, since=0):
        """Frames of the ID ``key`` (``s:123`` / ``x:18ff50e5`` / ``err``) after frame ``since``. The first call (or a
        new key) starts collecting — seeded with what the trace buffer still holds; WATCH_LEASE s without a call end it."""
        can_trace.check_keys([key])
        with self._lock:
            self.touch()
            if not self._sock:
                raise NetError(self.error or 'CAN socket is not open')
            if key != self._watch_key:
                self._watch_key = key
                self._watch_frames.clear()
                self._watch_frames.extend(f for f in self._frames if _key(f) == key)
            self._watch_seen = time.monotonic()
            frames = [f for f in self._watch_frames if f['id'] > since] if since else list(self._watch_frames)
            return {'frames': frames, 'next': self._next_id - 1, 'key': key, 'now': time.time(), 'error': self.error}

    def watch_stop(self):
        with self._lock:
            self._watch_key = None
            self._watch_frames.clear()

    def clear(self):
        with self._lock:
            self._frames.clear()
            self._ids.clear()
            self._totals = dict.fromkeys(self._totals, 0)


MAX_PROFILES = 50
MAX_TX_ROWS = 200
_UID = re.compile(r'^[\w-]{1,40}$')


FIELD_TYPES = ('bit', 'u8', 's8', 'u16', 's16', 'u32', 's32')
MAX_FIELDS = 32


def _check_fields(fields):
    """Fields of a TX row for the frame editor: {name, type, byte, bit, order le|be, scale, offset, min, max, step}."""
    out = []
    for f in (fields if isinstance(fields, list) else [])[:MAX_FIELDS]:
        if not isinstance(f, dict) or f.get('type') not in FIELD_TYPES:
            continue

        def num(key, default, lo=-1e15, hi=1e15):
            try:
                v = float(f.get(key, default))
            except (TypeError, ValueError):
                return default
            return default if v != v else max(lo, min(hi, v))         # NaN -> default
        item = {'name': str(f.get('name') or '')[:40], 'type': f['type'], 'byte': int(num('byte', 0, 0, 7)),
                'bit': int(num('bit', 0, 0, 7)), 'order': 'be' if f.get('order') == 'be' else 'le',
                'scale': num('scale', 1) or 1, 'offset': num('offset', 0), 'step': num('step', 1)}
        for key in ('min', 'max'):
            if f.get(key) not in (None, ''):
                item[key] = num(key, 0)
        if f.get('sweep') in ('up', 'down', 'both'):
            item['sweep'] = f['sweep']
        out.append(item)
    return out


def _row_mods(r):
    """cs / cnt of a TX row as stored (invalid values are dropped, not refused)."""
    out = {}
    if r.get('cs') in CHECKSUMS:
        out['cs'] = r['cs']
    try:
        if r.get('cnt'):
            check_mods('', r['cnt'])
            out['cnt'] = {'byte': int(r['cnt']['byte']), 'bits': r['cnt'].get('bits', '0-7')}
    except NetError:
        pass
    return out


def check_profiles(data):
    """Sanitise the CAN tab's TX lists: {profiles: [{name, tx: [rows], note}], current}. Row values are kept as
    typed (the front end validates them before sending; the server validates every frame it sends)."""
    profiles = (data or {}).get('profiles')
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise NetError('Bad profiles')
    out, names = [], set()
    s = lambda v, n=80: str(v if v is not None else '')[:n]     # noqa: E731
    for p in profiles:
        if not isinstance(p, dict):
            raise NetError('Bad profile')
        name = s(p.get('name'), 60).strip() or 'TX list'
        if name in names:
            raise NetError(f'Duplicate profile name: {name}')
        names.add(name)
        rows, uids = [], set()
        for r in (p.get('tx') if isinstance(p.get('tx'), list) else [])[:MAX_TX_ROWS]:
            if not isinstance(r, dict):
                continue
            uid = s(r.get('uid'), 40)
            if not _UID.match(uid) or uid in uids:
                uid = f'r{len(rows)}_{int(time.time() * 1000) % 100000000}'
            uids.add(uid)
            try:
                period = max(0, min(3600000, int(r.get('period') or 0)))
            except (TypeError, ValueError):
                period = 0
            rows.append({'uid': uid, 'name': s(r.get('name'), 60), 'id': s(r.get('id'), 12), 'ext': bool(r.get('ext')),
                         'rtr': bool(r.get('rtr')), 'data': s(r.get('data'), 40), 'period': period, 'on': bool(r.get('on')),
                         'fields': _check_fields(r.get('fields')), **_row_mods(r)})
        out.append({'name': name, 'tx': rows, 'note': s(p.get('note'), 20000)})
    current = s((data or {}).get('current'), 60)
    return {'profiles': out, 'current': current if current in names else (out[0]['name'] if out else '')}


def _key(f):
    """can_trace.frame_key of a recorded frame (error frames — also replayed ones — share ``err``)."""
    if f['dir'] == 'err' or f['error']:
        return 'err'
    return f"{'x' if f['ext'] else 's'}:{f['can_id']:x}"


def _public(d):
    return {k: v for k, v in d.items() if not k.startswith('_')}


def _speed(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise NetError('Speed must be a number')
    if not 0.05 <= v <= 100:
        raise NetError('Speed: 0.05 … 100')
    return v


_buses = {}
_buses_lock = threading.Lock()


def can_bus(iface):
    check_iface(iface, can=True)
    with _buses_lock:
        if iface not in _buses:
            _buses[iface] = CanBus(iface)
        return _buses[iface]


def stop_all_cyclic():
    """Stop every CAN transmission of the tool — cyclic sends and replays onto the bus (before a test script starts)."""
    with _buses_lock:
        buses = list(_buses.values())
    for bus in buses:
        bus.stop_tx()
