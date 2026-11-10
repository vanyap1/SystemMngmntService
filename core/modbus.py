"""Modbus master for HW Utils -> Modbus: read / write / scan over a serial port or the network. Stdlib + pyserial only.

Transports (``conn['transport']``):
  rtu      Modbus RTU on a serial port (USB-RS485 adapter, UART)          {port, baud, parity N|E|O, bytesize, stopbits}
  rtu_tcp  RTU frames (with CRC) over a TCP socket — transparent serial servers (ebyte, USR…) {host, netport}
  rtu_udp  RTU frames over UDP                                             {host, netport}
  tcp      Modbus TCP (MBAP header, no CRC) — devices / gateways on the LAN {host, netport}
  udp      Modbus UDP (MBAP over UDP)                                      {host, netport}
All take ``timeout`` (ms). Registers and bits travel as plain integers; the browser converts formats (u16, s32,
float32, word order). A link is opened per request batch (``run``) and closed again — no port stays claimed.
Serial access is refused while a test script runs (``blocked`` is set by routes/modbus.py).
"""
import re
import socket
import struct
import threading
import time

from core.session_files import SessionStore

try:
    import serial
    import serial.tools.list_ports as list_ports
except ImportError:          # pragma: no cover - pyserial comes with the panel (python3-serial)
    serial = None
    list_ports = None

TRANSPORTS = ('rtu', 'rtu_tcp', 'rtu_udp', 'tcp', 'udp')
BAUDS = (1200, 2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
FUNCS = {1: 'Read coils', 2: 'Read discrete inputs', 3: 'Read holding registers', 4: 'Read input registers',
         5: 'Write single coil', 6: 'Write single register', 15: 'Write multiple coils', 16: 'Write multiple registers'}
READ_LIMIT = {1: 2000, 2: 2000, 3: 125, 4: 125}
WRITE_LIMIT = {15: 1968, 16: 123}
EXCEPTIONS = {1: 'illegal function', 2: 'illegal data address', 3: 'illegal data value', 4: 'server device failure',
              5: 'acknowledge', 6: 'server device busy', 8: 'memory parity error', 10: 'gateway path unavailable',
              11: 'gateway target device failed to respond'}
_PORT = re.compile(r'^/dev/(tty[A-Za-z]+\d+|serial/by-(id|path)/[\w.:@+-]+|rfcomm\d+)$')
_HOST = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')
MAX_OPS = 64

blocked = lambda: None        # noqa: E731 - routes/modbus.py: message while a test script owns the serial ports
_locks = {}
_locks_guard = threading.Lock()


class ModbusError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class ModbusException(ModbusError):
    """The device answered with an exception code."""
    def __init__(self, fn, code):
        super().__init__(f'exception {code}: {EXCEPTIONS.get(code, "unknown")}', 200)
        self.code = code


def port_error(port, e):
    """Short message + status for a serial port that cannot be opened (pyserial repeats errno texts)."""
    text, no = str(e), getattr(e, 'errno', None)
    if no == 2 or 'No such file' in text:
        return f'{port} not found — unplugged?', 404
    if no == 13 or 'Permission denied' in text:
        return f'{port}: permission denied (group dialout?)', 403
    if 'Resource temporarily unavailable' in text or no in (11, 16):
        return f'{port} is in use (Terminal tab, another program?)', 409
    return f'Cannot open {port}: {text.split(": ")[-1]}', 502


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def ports():
    """Serial ports with a description (ttyS without hardware are left out by pyserial)."""
    if not list_ports:
        return []
    out = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        desc = p.description if p.description and p.description != 'n/a' else ''
        if not desc and p.device.startswith('/dev/ttyS'):
            desc = 'on-board UART'
        out.append({'device': p.device, 'description': desc, 'hwid': p.hwid if p.hwid != 'n/a' else ''})
    return out


# ── Connection settings ─────────────────────────────────────

def _int(v, lo, hi, what):
    try:
        v = int(str(v).strip(), 0)
    except (TypeError, ValueError):
        raise ModbusError(f'{what}: not a number')
    if not lo <= v <= hi:
        raise ModbusError(f'{what} must be {lo}…{hi}')
    return v


def check_conn(c):
    """Validated copy of a connection dict."""
    c = c or {}
    t = c.get('transport', 'rtu')
    if t not in TRANSPORTS:
        raise ModbusError(f'Unknown transport: {t}')
    out = {'transport': t, 'timeout': _int(c.get('timeout', 300), 20, 10000, 'Timeout (ms)')}
    if t == 'rtu':
        port = str(c.get('port') or '')
        if not _PORT.match(port):
            raise ModbusError(f'Invalid serial port: {port or "(none)"}')
        baud = _int(c.get('baud', 9600), 300, 4000000, 'Baud rate')
        parity = str(c.get('parity', 'N')).upper()
        if parity not in ('N', 'E', 'O'):
            raise ModbusError('Parity: N, E or O')
        out.update(port=port, baud=baud, parity=parity, bytesize=_int(c.get('bytesize', 8), 7, 8, 'Data bits'),
                   stopbits=_int(c.get('stopbits', 1), 1, 2, 'Stop bits'))
    else:
        host = str(c.get('host') or '').strip()
        if not _HOST.match(host):
            raise ModbusError(f'Invalid host: {host or "(none)"}')
        out.update(host=host, port=_int(c.get('netport', 502), 1, 65535, 'Port'))
    return out


def describe(c):
    if c['transport'] == 'rtu':
        return f"{c['port']} {c['baud']} {c['bytesize']}{c['parity']}{c['stopbits']}"
    return f"{c['transport']} {c['host']}:{c['port']}"


# ── Links ───────────────────────────────────────────────────

class Link:
    """One open transport; ``transact(unit, pdu)`` -> response PDU (raises on timeout / bad frame / exception)."""

    def __init__(self, conn):
        self.c = conn
        self.timeout = conn['timeout'] / 1000
        self.log = []           # [(dir, bytes)]
        self.dev = None
        self.tid = 0
        self.lock = None

    def __enter__(self):
        c = self.c
        if c['transport'] == 'rtu':
            msg = blocked()
            if msg:
                raise ModbusError(msg, 409)
            if serial is None:
                raise ModbusError('pyserial is not installed (python3-serial)', 500)
            with _locks_guard:
                self.lock = _locks.setdefault(c['port'], threading.Lock())
            if not self.lock.acquire(timeout=10):
                raise ModbusError(f'{c["port"]} is busy', 409)
            try:
                self.dev = serial.Serial(c['port'], c['baud'], bytesize=c['bytesize'], parity=c['parity'],
                                         stopbits=c['stopbits'], timeout=self.timeout, write_timeout=2, exclusive=True)
            except (serial.SerialException, OSError) as e:
                self.lock.release()
                raise ModbusError(*port_error(c['port'], e))
        else:
            kind = socket.SOCK_STREAM if c['transport'] in ('tcp', 'rtu_tcp') else socket.SOCK_DGRAM
            try:
                self.dev = socket.create_connection((c['host'], c['port']), timeout=max(self.timeout, 1.0)) \
                    if kind == socket.SOCK_STREAM else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                if kind == socket.SOCK_DGRAM:
                    self.dev.connect((socket.gethostbyname(c['host']), c['port']))
                self.dev.settimeout(self.timeout)
            except OSError as e:
                raise ModbusError(f'Cannot connect to {c["host"]}:{c["port"]}: {e.strerror or e}', 502)
        return self

    def __exit__(self, *a):
        try:
            if self.dev:
                self.dev.close()
        finally:
            if self.lock:
                self.lock.release()

    # framing ------------------------------------------------

    @property
    def rtu(self):
        return self.c['transport'] in ('rtu', 'rtu_tcp', 'rtu_udp')

    @property
    def stream(self):
        return self.c['transport'] in ('rtu', 'rtu_tcp', 'tcp')

    def _send(self, data):
        self.log.append(('tx', data))
        if self.c['transport'] == 'rtu':
            self.dev.reset_input_buffer()
            self.dev.write(data)
            self.dev.flush()
        else:
            if self.stream:
                self._drain()
            self.dev.send(data)

    def _drain(self):
        """Throw away stale bytes (a late answer to a timed-out request) before sending."""
        self.dev.setblocking(False)
        try:
            while self.dev.recv(4096):
                pass
        except (BlockingIOError, OSError):
            pass
        finally:
            self.dev.settimeout(self.timeout)

    def _read(self, n, deadline):
        """Exactly n bytes from a stream transport before the deadline."""
        buf = b''
        while len(buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            if self.c['transport'] == 'rtu':
                self.dev.timeout = left
                chunk = self.dev.read(n - len(buf))
            else:
                self.dev.settimeout(left)
                try:
                    chunk = self.dev.recv(n - len(buf))
                except socket.timeout:
                    break
                if not chunk:
                    raise ModbusError('Connection closed by the device', 502)
            buf += chunk
        if len(buf) < n:
            if buf:
                self.log.append(('rx', buf))
            raise ModbusError('timeout — no answer' if not buf else f'timeout — incomplete answer ({len(buf)} bytes)', 504)
        return buf

    def _rest_len(self, fn, head):
        """Bytes after unit + function (+ byte count for reads) in an RTU answer, CRC included."""
        if fn & 0x80:
            return 3
        if fn in (1, 2, 3, 4):
            return head + 2
        return 6

    def transact(self, unit, pdu):
        fn = pdu[0]
        deadline = time.monotonic() + self.timeout
        if self.rtu:
            frame = bytes([unit]) + pdu
            frame += struct.pack('<H', crc16(frame))
            self._send(frame)
            if unit == 0:
                return None                  # broadcast: no answer
            if self.c['transport'] == 'rtu_udp':
                rx = self._recv_dgram(deadline)
            else:
                rx = self._read(2, deadline)
                if rx[1] in (1, 2, 3, 4):
                    rx += self._read(1, deadline)
                    rx += self._read(rx[2] + 2, deadline)
                else:
                    rx += self._read(self._rest_len(rx[1], 0), deadline)
            self.log.append(('rx', rx))
            if len(rx) < 5 or crc16(rx[:-2]) != struct.unpack('<H', rx[-2:])[0]:
                raise ModbusError('CRC error in the answer', 502)
            if rx[0] != unit:
                raise ModbusError(f'answer from unit {rx[0]} instead of {unit}', 502)
            body = rx[1:-2]
        else:
            self.tid = (self.tid + 1) & 0xFFFF
            frame = struct.pack('>HHHB', self.tid, 0, len(pdu) + 1, unit) + pdu
            self._send(frame)
            if self.c['transport'] == 'udp':
                rx = self._recv_dgram(deadline)
            else:
                rx = self._read(7, deadline)
                rx += self._read(struct.unpack('>H', rx[4:6])[0] - 1, deadline)
            self.log.append(('rx', rx))
            if len(rx) < 9:
                raise ModbusError('short answer', 502)
            tid, proto = struct.unpack('>HH', rx[:4])
            if tid != self.tid or proto != 0:
                raise ModbusError('answer to another request (transaction id)', 502)
            body = rx[7:]
        if body[0] == fn | 0x80:
            raise ModbusException(fn, body[1] if len(body) > 1 else 0)
        if body[0] != fn:
            raise ModbusError(f'answer with function {body[0]} instead of {fn}', 502)
        return body

    def _recv_dgram(self, deadline):
        self.dev.settimeout(max(0.001, deadline - time.monotonic()))
        try:
            return self.dev.recv(512)
        except socket.timeout:
            raise ModbusError('timeout — no answer', 504)


# ── Requests ────────────────────────────────────────────────

def _bits(data, count):
    return [(data[i // 8] >> (i % 8)) & 1 for i in range(count)]


def check_op(op):
    """Validated copy of one request {unit, fn, addr, count, values}."""
    op = op or {}
    fn = _int(op.get('fn', 3), 1, 16, 'Function')
    if fn not in FUNCS:
        raise ModbusError(f'Unsupported function {fn}')
    unit = _int(op.get('unit', 1), 0, 255, 'Unit id')
    addr = _int(op.get('addr', 0), 0, 0xFFFF, 'Address')
    out = {'fn': fn, 'unit': unit, 'addr': addr}
    if fn in READ_LIMIT:
        if unit == 0:
            raise ModbusError('Unit 0 (broadcast) only for writes')
        out['count'] = _int(op.get('count', 1), 1, READ_LIMIT[fn], 'Count')
        if addr + out['count'] > 0x10000:
            raise ModbusError('Address + count beyond 65535')
    else:
        vals = op.get('values')
        if not isinstance(vals, list) or not vals:
            raise ModbusError('No values to write')
        lim = 1 if fn in (5, 6) else WRITE_LIMIT[fn]
        if len(vals) > lim:
            raise ModbusError(f'At most {lim} value(s) for function {fn}')
        top = 1 if fn in (5, 15) else 0xFFFF
        out['values'] = [_int(v, 0, top, 'Value') for v in vals]
    return out


def pdu_of(op):
    fn, addr = op['fn'], op['addr']
    if fn in READ_LIMIT:
        return struct.pack('>BHH', fn, addr, op['count'])
    v = op['values']
    if fn == 5:
        return struct.pack('>BHH', fn, addr, 0xFF00 if v[0] else 0)
    if fn == 6:
        return struct.pack('>BHH', fn, addr, v[0])
    if fn == 15:
        data = bytearray((len(v) + 7) // 8)
        for i, b in enumerate(v):
            if b:
                data[i // 8] |= 1 << (i % 8)
        return struct.pack('>BHHB', fn, addr, len(v), len(data)) + bytes(data)
    return struct.pack('>BHHB', fn, addr, len(v), len(v) * 2) + b''.join(struct.pack('>H', x) for x in v)


def parse(op, body):
    fn = op['fn']
    if fn in (1, 2):
        return _bits(body[2:2 + body[1]], op['count'])
    if fn in (3, 4):
        n = body[1] // 2
        if n != op['count']:
            raise ModbusError(f'{n} register(s) instead of {op["count"]}', 502)
        return list(struct.unpack(f'>{n}H', body[2:2 + 2 * n]))
    return None


def _hex(b):
    return ' '.join(f'{x:02X}' for x in b)


def run(conn, ops, gap_ms=0):
    """Execute requests over one link; every op gets {ok, values | error, code, ms, tx, rx} (a failure doesn't stop the rest)."""
    conn = check_conn(conn)
    if not isinstance(ops, list) or not ops:
        raise ModbusError('Nothing to do')
    if len(ops) > MAX_OPS:
        raise ModbusError(f'At most {MAX_OPS} requests at once')
    checked = []
    for i, op in enumerate(ops):
        try:
            checked.append(check_op(op))
        except ModbusError as e:
            checked.append({'error': str(e)})
    results = []
    with Link(conn) as link:
        for i, op in enumerate(checked):
            if 'error' in op:
                results.append({'ok': False, 'error': op['error'], 'ms': 0})
                continue
            if i and gap_ms:
                time.sleep(gap_ms / 1000)
            link.log = []
            t0 = time.monotonic()
            r = {'ok': False}
            try:
                body = link.transact(op['unit'], pdu_of(op))
                r = {'ok': True, 'values': parse(op, body) if body is not None else None, 'broadcast': body is None}
            except ModbusException as e:
                r = {'ok': False, 'error': str(e), 'code': e.code}
            except ModbusError as e:
                r = {'ok': False, 'error': str(e)}
            except (OSError, ValueError) as e:
                r = {'ok': False, 'error': f'I/O error: {e}'}
            r['ms'] = round((time.monotonic() - t0) * 1000, 1)
            r['tx'] = ' | '.join(_hex(b) for d, b in link.log if d == 'tx')
            r['rx'] = ' | '.join(_hex(b) for d, b in link.log if d == 'rx')
            results.append(r)
    return {'conn': describe(conn), 'results': results, 'time': time.time()}


def scan(conn, first=1, last=247, fn=3, addr=0, timeout=None):
    """Probe unit ids first..last with one read; an answer — even an exception — means a device is there."""
    conn = check_conn(conn)
    first, last = _int(first, 1, 247, 'From'), _int(last, 1, 247, 'To')
    if last < first or last - first > 63:
        raise ModbusError('Scan at most 64 unit ids per request')
    fn = _int(fn, 1, 4, 'Function')
    addr = _int(addr, 0, 0xFFFF, 'Address')
    if timeout is not None:
        conn['timeout'] = _int(timeout, 20, 5000, 'Timeout (ms)')
    found = []
    with Link(conn) as link:
        for unit in range(first, last + 1):
            link.log = []
            t0 = time.monotonic()
            try:
                link.transact(unit, struct.pack('>BHH', fn, addr, 1))
                found.append({'unit': unit, 'ok': True, 'ms': round((time.monotonic() - t0) * 1000, 1)})
            except ModbusException as e:
                found.append({'unit': unit, 'ok': False, 'error': str(e), 'ms': round((time.monotonic() - t0) * 1000, 1)})
            except ModbusError as e:
                if 'CRC' in str(e) or 'unit' in str(e):         # garbage on the line: report, keep scanning
                    found.append({'unit': unit, 'ok': False, 'error': str(e), 'noise': True})
            except (OSError, ValueError):
                pass
            if conn['transport'] == 'rtu':
                time.sleep(0.005)
    return {'conn': describe(conn), 'first': first, 'last': last, 'found': found}


# ── Profiles (config ``modbus`` of this host) ──────────────

MAX_PROFILES, MAX_MACROS = 30, 300
_FMT = re.compile(r'^[a-z0-9_]{1,16}$')


def _s(v, n=80):
    return str(v if v is not None else '')[:n]


def check_profiles(data):
    """Sanitised {'profiles': [{name, conn, macros, period}], 'current'} for config.json."""
    profiles = (data or {}).get('profiles')
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise ModbusError('Bad profiles')
    out, names = [], set()
    for p in profiles:
        if not isinstance(p, dict):
            raise ModbusError('Bad profile')
        name = _s(p.get('name'), 60).strip() or 'Profile'
        if name in names:
            raise ModbusError(f'Duplicate profile name: {name}')
        names.add(name)
        c = p.get('conn') if isinstance(p.get('conn'), dict) else {}
        conn = {k: _s(c.get(k), 120) for k in ('transport', 'port', 'baud', 'parity', 'bytesize', 'stopbits', 'host',
                                                'netport', 'timeout') if c.get(k) is not None}
        macros = p.get('macros') if isinstance(p.get('macros'), list) else []
        if len(macros) > MAX_MACROS:
            raise ModbusError(f'At most {MAX_MACROS} macros per profile')
        ms = []
        for m in macros:
            if not isinstance(m, dict):
                continue
            fmt = _s(m.get('fmt'), 16)
            try:
                every = max(50, min(3600000, int(m.get('period') or 0))) if m.get('period') else None
            except (TypeError, ValueError):
                every = None
            row = {'name': _s(m.get('name'), 60), 'unit': _s(m.get('unit'), 8), 'fn': _s(m.get('fn'), 4),
                   'addr': _s(m.get('addr'), 12), 'count': _s(m.get('count'), 8), 'values': _s(m.get('values'), 2000),
                   'fmt': fmt if _FMT.match(fmt) else 'u16', 'cycle': bool(m.get('cycle')), 'note': _s(m.get('note'), 200),
                   'auto': bool(m.get('auto', m.get('cycle')))}       # old profiles: rows marked for Cycle = timer rows
            if every:
                row['period'] = every
            ms.append(row)
        try:
            period = max(50, min(3600000, int(p.get('period') or 1000)))
        except (TypeError, ValueError):
            period = 1000
        out.append({'name': name, 'conn': conn, 'macros': ms, 'period': period, 'note': _s(p.get('note'), 20000)})
    current = _s((data or {}).get('current'), 60)
    return {'profiles': out, 'current': current if current in names else (out[0]['name'] if out else '')}


# ── Sessions (config.modbus_sessions_dir()/<slug>.json, core/session_files.py) ────

def _sessions_dir():
    from core import config
    return config.modbus_sessions_dir()


_store = SessionStore(_sessions_dir, ModbusError, 'macros')


def list_sessions():
    return _store.list()


def save_session(name, data, overwrite=False):
    """Write {profile, results, log, found, note} under ``name``; 409 when it exists and ``overwrite`` is false."""
    _, name = _store.slug(name)
    data = data if isinstance(data, dict) else {}
    prof = check_profiles({'profiles': [dict(data.get('profile') or {}, name=name)]})['profiles'][0]
    lst = lambda k: data.get(k) if isinstance(data.get(k), list) else []     # noqa: E731
    return _store.save(name, {'profile': prof, 'results': lst('results'), 'log': lst('log'), 'found': lst('found'),
                              'note': str(data.get('note') or '')[:20000]}, overwrite)


def load_session(name):
    return _store.load(name)


def delete_session(name):
    return _store.delete(name)
