"""Raw data terminal for HW Utils -> Terminal: a serial port, a TCP client or a UDP socket kept open while used.

Each open connection is a ``Session`` with a reader thread that stores everything received (and what was sent)
as numbered chunks {i, t, dir: rx|tx|sys, data, src}; the browser polls ``read(id, since)``. A session closes on
``close()``, when the device / peer goes away, or LEASE_SECONDS after the last poll (closed tab) — nothing stays
claimed. Serial ports are opened exclusively (flock), so the Modbus tool and the terminal never share a port by
accident; they are refused while a test script runs (``blocked`` is set by routes/ttyterm.py).
"""
import base64
import collections
import socket
import threading
import time
import uuid

from core import modbus
from core.session_files import SessionStore

try:
    import serial
except ImportError:          # pragma: no cover
    serial = None

TRANSPORTS = ('serial', 'tcp', 'udp')
MAX_SESSIONS = 4
LEASE_SECONDS = 30
MAX_CHUNKS = 20000
MAX_BYTES = 4 * 1024 * 1024
MAX_SEND = 64 * 1024
# Flood guard (video stream, wrong port …): above these rates per second nothing is stored or sent to the browser,
# reading is slowed down (TCP throttles the sender, the kernel drops surplus UDP), counted as "dropped".
FLOOD_BYTES = 256 * 1024
FLOOD_CHUNKS = 1000

blocked = lambda: None        # noqa: E731
_sessions = {}
_lock = threading.Lock()


class TtyError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def check_conn(c):
    c = c or {}
    t = c.get('transport', 'serial')
    if t not in TRANSPORTS:
        raise TtyError(f'Unknown transport: {t}')
    try:
        if t == 'serial':
            m = modbus.check_conn(dict(c, transport='rtu'))
            return {'transport': t, 'port': m['port'], 'baud': m['baud'], 'parity': m['parity'],
                    'bytesize': m['bytesize'], 'stopbits': m['stopbits']}
        out = {'transport': t}
        if t == 'tcp':
            m = modbus.check_conn({'transport': 'tcp', 'host': c.get('host'), 'netport': c.get('netport')})
            out.update(host=m['host'], port=m['port'])
        else:
            listen = modbus._int(c.get('listen') or 0, 0, 65535, 'Listen port')    # 0 = auto (a free port)
            host = str(c.get('host') or '').strip()
            if host:
                m = modbus.check_conn({'transport': 'udp', 'host': host, 'netport': c.get('netport')})
                out.update(host=m['host'], port=m['port'])
            out['listen'] = listen
        return out
    except modbus.ModbusError as e:
        raise TtyError(str(e))


def describe(c):
    if c['transport'] == 'serial':
        return f"{c['port']} {c['baud']} {c['bytesize']}{c['parity']}{c['stopbits']}"
    if c['transport'] == 'tcp':
        return f"tcp {c['host']}:{c['port']}"
    return 'udp' + (f" → {c['host']}:{c['port']}" if c.get('host') else '') + (f" · listen :{c['listen']}" if c.get('listen') else ' · listen auto')


class Session:
    def __init__(self, conn):
        self.id = uuid.uuid4().hex[:12]
        self.conn = conn
        self.title = describe(conn)
        self.dev = None
        self.chunks = collections.deque()
        self.next = 0
        self.size = 0
        self.rx_bytes = self.tx_bytes = 0
        self.closed = False
        self.error = ''
        self.opened = time.time()
        self.last_seen = time.time()
        self.lock = threading.Lock()
        self.wlock = threading.Lock()
        self.local = ''
        self.flood = False
        self.dropped = 0                 # bytes not stored because of the flood guard
        self._win = [time.time(), 0, 0]  # window start, bytes, chunks
        self._quiet = 0                  # calm seconds in a row while in flood mode

    # buffer -----------------------------------------------

    def add(self, direction, data, src=''):
        with self.lock:
            self.chunks.append((self.next, time.time(), direction, data, src))
            self.next += 1
            self.size += len(data)
            while self.chunks and (len(self.chunks) > MAX_CHUNKS or self.size > MAX_BYTES):
                self.size -= len(self.chunks.popleft()[3])

    def read(self, since=0, limit=2000):
        self.last_seen = time.time()
        with self.lock:
            out = [c for c in self.chunks if c[0] >= since][:limit]
            nxt = out[-1][0] + 1 if out else min(max(since, 0), self.next)
        return {'id': self.id, 'chunks': [{'i': i, 't': t, 'dir': d, 'b64': base64.b64encode(b).decode(), 'src': s}
                                          for i, t, d, b, s in out],
                'next': nxt, 'more': bool(out) and out[-1][0] + 1 < self.next, 'state': self.state()}

    def state(self):
        return {'id': self.id, 'title': self.title, 'conn': self.conn, 'closed': self.closed, 'error': self.error,
                'opened': self.opened, 'rx': self.rx_bytes, 'tx': self.tx_bytes, 'local': self.local,
                'flood': self.flood, 'dropped': self.dropped,
                'lines': self.lines() if self.conn['transport'] == 'serial' and not self.closed else None}

    # device -----------------------------------------------

    def open(self):
        c = self.conn
        try:
            if c['transport'] == 'serial':
                msg = modbus.blocked()
                if msg:
                    raise TtyError(msg, 409)
                if serial is None:
                    raise TtyError('pyserial is not installed (python3-serial)', 500)
                try:
                    self.dev = serial.Serial(c['port'], c['baud'], bytesize=c['bytesize'], parity=c['parity'],
                                             stopbits=c['stopbits'], timeout=0.05, write_timeout=2, exclusive=True)
                except (serial.SerialException, OSError) as e:
                    raise TtyError(*modbus.port_error(c['port'], e))
            elif c['transport'] == 'tcp':
                try:
                    self.dev = socket.create_connection((c['host'], c['port']), timeout=5)
                except OSError as e:
                    raise TtyError(f'Cannot connect to {c["host"]}:{c["port"]}: {e.strerror or e}', 502)
                self.dev.settimeout(0.2)
                self.local = '%s:%d' % self.dev.getsockname()[:2]
            else:
                self.dev = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.dev.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    self.dev.bind(('0.0.0.0', c['listen']))
                except OSError as e:
                    self.dev.close()
                    raise TtyError(f'Cannot listen on UDP port {c["listen"]}: {e.strerror or e}', 409)
                self.dev.settimeout(0.2)
                self.local = 'udp :%d' % self.dev.getsockname()[1]
        except TtyError:
            self.closed = True
            raise
        self.add('sys', f'opened {self.title}'.encode() + (f' (local {self.local})'.encode() if self.local else b''))
        threading.Thread(target=self._reader, name=f'tty-{self.id}', daemon=True).start()

    def _reader(self):
        t = self.conn['transport']
        try:
            while not self.closed:
                if time.time() - self.last_seen > LEASE_SECONDS:
                    self.add('sys', b'closed: nobody reads (tab closed)')
                    break
                try:
                    if t == 'serial':
                        n = self.dev.in_waiting
                        data = self.dev.read(n or 1)
                        src = ''
                        if not data and self.flood:
                            self._guard(0, 0)
                    elif t == 'tcp':
                        data = self.dev.recv(65536)
                        src = ''
                        if not data:
                            self.error = 'connection closed by the peer'
                            self.add('sys', b'closed by the peer')
                            break
                    else:
                        data, addr = self.dev.recvfrom(65536)
                        src = '%s:%d' % addr[:2]
                except socket.timeout:
                    if self.flood:
                        self._guard(0, 0)         # quiet again: leave the flood mode
                    continue
                except (OSError, ValueError) as e:
                    if not self.closed:
                        self.error = str(getattr(e, 'strerror', '') or e)
                        self.add('sys', f'error: {self.error}'.encode())
                    break
                except Exception as e:     # serial.SerialException (device unplugged …)
                    if not self.closed:
                        self.error = str(e)
                        self.add('sys', f'error: {self.error}'.encode())
                    break
                if data:
                    self.rx_bytes += len(data)
                    self._guard(len(data))
                    if self.flood:
                        self.dropped += len(data)
                        self._drain()
                    else:
                        self.add('rx', data, src)
        finally:
            self._shutdown()

    def _drain(self):
        """Flood mode: take whatever is pending at once (counted, not stored), then pause — cheap on the CPU while
        the measured rate stays the real one (the kernel drops surplus UDP while we sleep)."""
        n = k = 0
        try:
            if self.conn['transport'] == 'serial':
                pending = self.dev.in_waiting
                if pending:
                    n, k = len(self.dev.read(pending)), 1
            else:
                for _ in range(300):                      # the rest is dropped by the kernel
                    data = self.dev.recv(65536, socket.MSG_DONTWAIT)
                    if not data:
                        break
                    n += len(data)
                    k += 1
        except (BlockingIOError, InterruptedError):
            pass
        except Exception:
            return
        if n:
            self.rx_bytes += n
            self.dropped += n
            self._guard(n, k)
        time.sleep(0.1)

    def _guard(self, n, chunks=1):
        """Per-second rate check: switch the flood mode on above FLOOD_* and off when the rate is back below."""
        w = self._win
        w[1] += n
        w[2] += chunks
        now = time.time()
        if now - w[0] < 1.0 and not (w[1] > FLOOD_BYTES or w[2] > FLOOD_CHUNKS):
            return
        span = max(now - w[0], 0.001)
        rate, count = w[1] / span, w[2] / span
        over = w[1] > FLOOD_BYTES or w[2] > FLOOD_CHUNKS
        self._quiet = 0 if over else self._quiet + (1 if now - w[0] >= 1.0 else 0)
        if over and not self.flood:
            self.flood = True
            self.add('sys', f'flood guard: {rate / 1024:.0f} KB/s, {count:.0f} packets/s — data is counted but not shown '
                            f'(limit {FLOOD_BYTES // 1024} KB/s, {FLOOD_CHUNKS}/s)'.encode())
        elif not over and self.flood and self._quiet >= 2:      # two calm seconds in a row
            self.flood = False
            self.add('sys', f'flood guard: rate back to normal, {self.dropped} bytes were dropped'.encode())
        if now - w[0] >= 1.0 or over:
            self._win = [now, 0, 0]

    def _shutdown(self):
        self.closed = True
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass

    def send(self, data, to=None):
        if self.closed:
            raise TtyError('The connection is closed', 409)
        if not data:
            raise TtyError('Nothing to send')
        if len(data) > MAX_SEND:
            raise TtyError(f'At most {MAX_SEND} bytes at once')
        c = self.conn
        host, port = to or (c.get('host'), c.get('port'))
        if c['transport'] == 'udp' and not host:
            raise TtyError('UDP: no remote host / port to send to')
        dest = f'{host}:{port}' if c['transport'] == 'udp' else ''
        with self.wlock:
            self.add('tx', data, dest)          # before sending: a fast reply / close must come after it in the log
            try:
                if c['transport'] == 'serial':
                    self.dev.write(data)
                    self.dev.flush()
                elif c['transport'] == 'tcp':
                    self.dev.sendall(data)
                else:
                    self.dev.sendto(data, (socket.gethostbyname(host), port))
            except Exception as e:
                self.add('sys', f'send failed: {e}'.encode())
                raise TtyError(f'Send failed: {e}', 502)
        self.tx_bytes += len(data)
        self.last_seen = time.time()
        return self.state()

    def lines(self):
        try:
            return {'dtr': bool(self.dev.dtr), 'rts': bool(self.dev.rts), 'cts': bool(self.dev.cts), 'dsr': bool(self.dev.dsr)}
        except Exception:
            return None

    def set_lines(self, dtr=None, rts=None):
        if self.conn['transport'] != 'serial' or self.closed:
            raise TtyError('Not an open serial port', 409)
        try:
            if dtr is not None:
                self.dev.dtr = bool(dtr)
            if rts is not None:
                self.dev.rts = bool(rts)
        except Exception as e:
            raise TtyError(f'This port has no modem lines: {e}', 409)
        self.add('sys', f'DTR={int(self.dev.dtr)} RTS={int(self.dev.rts)}'.encode())
        return self.state()

    def close(self):
        if not self.closed:
            self.closed = True
            self.add('sys', b'closed')
        self._shutdown()


# ── Registry ────────────────────────────────────────────────

def _prune():
    for sid in [k for k, s in _sessions.items() if s.closed and time.time() - s.last_seen > LEASE_SECONDS]:
        _sessions.pop(sid, None)


def open_session(conn):
    conn = check_conn(conn)
    with _lock:
        _prune()
        if sum(1 for s in _sessions.values() if not s.closed) >= MAX_SESSIONS:
            raise TtyError(f'At most {MAX_SESSIONS} connections open — close one', 429)
        s = Session(conn)
        s.open()
        _sessions[s.id] = s
    return s.state()


def get(sid):
    s = _sessions.get(sid or '')
    if not s:
        raise TtyError('Connection not found (closed?)', 404)
    return s


def sessions():
    with _lock:
        _prune()
        return [s.state() for s in _sessions.values()]


def close(sid):
    s = get(sid)
    s.close()
    return s.state()


def close_all():
    for s in list(_sessions.values()):
        s.close()


def oneshot(conn, data, wait=True, timeout_ms=1000, idle_ms=250):
    """Open, send ``data``, collect the reply, close — for a send while no connection is open (e.g. SCPI over TCP,
    one connection per command). The reply ends when the peer closes, ``idle_ms`` after its last byte, or at
    ``timeout_ms``. Returns {chunks (like read()), ms, end: closed|idle|timeout|sent, state}."""
    conn = check_conn(conn)
    try:
        timeout_ms = max(50, min(30000, int(timeout_ms)))
    except (TypeError, ValueError):
        raise TtyError('Reply timeout: a number of ms')
    s = Session(conn)
    t0 = time.monotonic()
    s.open()
    end = 'sent'
    try:
        s.send(data)
        if wait:
            end = 'timeout'
            while time.monotonic() - t0 < timeout_ms / 1000:
                s.last_seen = time.time()
                if s.closed:
                    end = 'closed'
                    break
                with s.lock:
                    last_rx = next((c[1] for c in reversed(s.chunks) if c[2] == 'rx'), None)
                if last_rx and time.time() - last_rx > idle_ms / 1000:
                    end = 'idle'
                    break
                time.sleep(0.01)
    finally:
        s.close()
    d = s.read(0, limit=5000)
    ms = round((time.monotonic() - t0) * 1000)
    d['chunks'] = [c for c in d['chunks'] if not (c['dir'] == 'sys' and base64.b64decode(c['b64']) == b'closed')]
    return {'chunks': d['chunks'], 'ms': ms, 'end': end, 'state': s.state()}


def decode_payload(text, is_hex):
    """The send field -> bytes ('48 65 0x6C,6c' in hex mode; text is UTF-8 with \\n \\r \\t \\xNN escapes)."""
    if is_hex:
        toks = text.replace(',', ' ').split()
        try:
            return bytes(int(t[2:] if t.lower().startswith('0x') else t, 16) for t in toks) if toks else b''
        except ValueError:
            raise TtyError('Hex: bytes like "48 65 6C 0x6C"')
    out, i = bytearray(), 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            n = text[i + 1]
            if n in 'nrt0\\':
                out += {'n': b'\n', 'r': b'\r', 't': b'\t', '0': b'\0', '\\': b'\\'}[n]
                i += 2
                continue
            hx = text[i + 2:i + 4]
            if n == 'x' and len(hx) == 2 and all(c in '0123456789abcdefABCDEF' for c in hx):
                out.append(int(text[i + 2:i + 4], 16))
                i += 4
                continue
        out += ch.encode('utf-8')
        i += 1
    return bytes(out)


# ── Profiles (config ``tty`` of this host) ─────────────────

MAX_PROFILES, MAX_COMMANDS = 30, 200
EOLS = ('', 'lf', 'cr', 'crlf')


def check_profiles(data):
    profiles = (data or {}).get('profiles')
    if not isinstance(profiles, list) or len(profiles) > MAX_PROFILES:
        raise TtyError('Bad profiles')
    out, names = [], set()
    s = lambda v, n=80: str(v if v is not None else '')[:n]     # noqa: E731
    for p in profiles:
        if not isinstance(p, dict):
            raise TtyError('Bad profile')
        name = s(p.get('name'), 60).strip() or 'Profile'
        if name in names:
            raise TtyError(f'Duplicate profile name: {name}')
        names.add(name)
        c = p.get('conn') if isinstance(p.get('conn'), dict) else {}
        conn = {k: s(c.get(k), 120) for k in ('transport', 'port', 'baud', 'parity', 'bytesize', 'stopbits', 'host',
                                                'netport', 'listen') if c.get(k) is not None}
        cmds = []
        for m in (p.get('commands') if isinstance(p.get('commands'), list) else [])[:MAX_COMMANDS]:
            if not isinstance(m, dict):
                continue
            try:
                period = max(50, min(3600000, int(m.get('period') or 1000)))
            except (TypeError, ValueError):
                period = 1000
            cmds.append({'name': s(m.get('name'), 60), 'data': s(m.get('data'), 4000), 'hex': bool(m.get('hex')),
                         'eol': m.get('eol') if m.get('eol') in EOLS else 'lf', 'period': period, 'timer': bool(m.get('timer')),
                         'wait': m.get('wait') is not False})
        view = p.get('view') if isinstance(p.get('view'), dict) else {}
        try:
            reply_ms = max(50, min(30000, int(p.get('replyMs') or 1000)))
        except (TypeError, ValueError):
            reply_ms = 1000
        out.append({'name': name, 'conn': conn, 'eol': p.get('eol') if p.get('eol') in EOLS else 'lf', 'commands': cmds,
                    'wait': p.get('wait') is not False, 'replyMs': reply_ms, 'note': s(p.get('note'), 20000),
                    'view': {k: bool(view.get(k)) for k in ('hex', 'time', 'tx', 'json', 'wrap') if k in view}})
    current = s((data or {}).get('current'), 60)
    return {'profiles': out, 'current': current if current in names else (out[0]['name'] if out else '')}


# ── Sessions (config.tty_sessions_dir()/<slug>.json) ───────

def _sessions_dir():
    from core import config
    return config.tty_sessions_dir()


_store = SessionStore(_sessions_dir, TtyError, 'commands')
MAX_SAVED_LINES = 5000


def list_sessions():
    return _store.list()


def save_session(name, data, overwrite=False):
    """{profile, lines: [{t, dir, text, src}], note} under ``name`` (409 when it exists and ``overwrite`` is false)."""
    _, name = _store.slug(name)
    data = data if isinstance(data, dict) else {}
    prof = check_profiles({'profiles': [dict(data.get('profile') or {}, name=name)]})['profiles'][0]
    lines = []
    for l in (data.get('lines') if isinstance(data.get('lines'), list) else [])[-MAX_SAVED_LINES:]:
        if isinstance(l, dict) and l.get('dir') in ('rx', 'tx', 'sys'):
            try:
                t = float(l.get('t') or 0)
            except (TypeError, ValueError):
                t = 0
            lines.append({'t': t, 'dir': l['dir'], 'text': str(l.get('text') or '')[:20000], 'src': str(l.get('src') or '')[:60]})
    return _store.save(name, {'profile': prof, 'lines': lines, 'note': str(data.get('note') or '')[:20000]}, overwrite)


def load_session(name):
    return _store.load(name)


def delete_session(name):
    return _store.delete(name)
