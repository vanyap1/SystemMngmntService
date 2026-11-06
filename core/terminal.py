"""Interactive terminal of the code editor: a login shell in a pseudo-terminal (like PuTTY / an SSH session).

Full-screen console programs (mc, htop, nano, vim, less, top) work: keys go to the pty unchanged, the window size
is passed on (TIOCSWINSZ → SIGWINCH), the output (escape sequences included) is streamed to xterm.js.

Transport without websockets (offline, Flask dev server): the browser reads the output as Server-Sent Events
(GET /api/term/stream, byte offsets so a reconnect resumes without gaps) and sends keys with small POSTs.

The shell runs as the owner of target_dir (root only if target_dir belongs to root), in target_dir, with
TERM=xterm-256color and a UTF-8 locale. A session lives while a page streams it; without a reader it is closed
after IDLE_SECONDS (a page reload reattaches in time). Children die with the panel (core/spawn.py).
"""
import codecs
import fcntl
import os
import pty
import pwd
import secrets
import signal
import struct
import termios
import threading
import time

from core import config, spawn

MAX_SESSIONS = 8
BUFFER = 256 * 1024          # output kept for a reattach (bytes)
IDLE_SECONDS = 60            # no stream connected for this long -> the shell is closed


class TermError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _ctty():
    """preexec (after start_new_session's setsid): the pty becomes the controlling terminal (Ctrl+C, job control)."""
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass


def shell_user():
    """pwd entry the shell runs as: the owner of target_dir when the panel is root, else the panel's user."""
    if os.geteuid() != 0:
        return pwd.getpwuid(os.geteuid())
    try:
        uid = os.stat(config.target_dir()).st_uid
        return pwd.getpwuid(uid)
    except (OSError, KeyError):
        return pwd.getpwuid(0)


class Session:
    def __init__(self, cols=120, rows=30):
        self.id = secrets.token_hex(8)
        self.created = time.time()
        self.last_seen = time.time()
        self.readers = 0
        self.closed = False
        self.exit_code = None
        self._buf = bytearray()
        self._start = 0                 # byte offset of _buf[0] in the whole output
        self._cond = threading.Condition()
        user = shell_user()
        self.user = user.pw_name
        cwd = config.target_dir() if os.path.isdir(config.target_dir()) else user.pw_dir
        shell = user.pw_shell if user.pw_shell and os.path.exists(user.pw_shell) and 'nologin' not in user.pw_shell \
            else '/bin/bash'
        env = {
            'TERM': 'xterm-256color', 'COLORTERM': 'truecolor',
            'HOME': user.pw_dir, 'USER': user.pw_name, 'LOGNAME': user.pw_name, 'SHELL': shell,
            'PATH': os.environ.get('PATH', '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'),
            'LANG': os.environ.get('LANG') or 'C.UTF-8',
        }
        if os.environ.get('LC_ALL'):
            env['LC_ALL'] = os.environ['LC_ALL']
        master, slave = pty.openpty()
        self._master = master
        self.resize(cols, rows)
        kw = {}
        if os.geteuid() == 0 and user.pw_uid != 0:
            kw = {'user': user.pw_uid, 'group': user.pw_gid,
                  'extra_groups': os.getgrouplist(user.pw_name, user.pw_gid)}
        try:
            self.proc = spawn.popen([shell, '-l'], stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
                                    start_new_session=True, setup=_ctty, close_fds=True, **kw)
        except OSError as e:
            os.close(master)
            os.close(slave)
            raise TermError(f'Cannot start {shell}: {e}', 500)
        finally:
            try:
                os.close(slave)
            except OSError:
                pass
        threading.Thread(target=self._pump, name=f'term-{self.id}', daemon=True).start()

    # ── output ──
    def _pump(self):
        while True:
            try:
                data = os.read(self._master, 65536)
            except OSError:                 # EIO: the shell (and everything on the pty) has exited
                break
            if not data:
                break
            with self._cond:
                self._buf += data
                extra = len(self._buf) - BUFFER
                if extra > 0:
                    del self._buf[:extra]
                    self._start += extra
                self._cond.notify_all()
        code = self.proc.wait()
        with self._cond:
            self.exit_code = code if code >= 0 else 128 - code
            self.closed = True
            self._cond.notify_all()
        try:
            os.close(self._master)
        except OSError:
            pass

    @property
    def end(self):
        return self._start + len(self._buf)

    def read(self, offset, timeout=15.0):
        """Output after byte `offset` (waits up to `timeout`). Returns (bytes, new_offset, closed)."""
        with self._cond:
            if offset >= self.end and not self.closed:
                self._cond.wait(timeout)
            offset = max(offset, self._start)          # older output was dropped from the buffer
            data = bytes(self._buf[offset - self._start:])
            return data, offset + len(data), self.closed and offset + len(data) >= self.end

    # ── input / control ──
    def write(self, text):
        if self.closed:
            raise TermError('The shell has exited', 409)
        data = text.encode('utf-8')
        while data:
            n = os.write(self._master, data)
            data = data[n:]
        self.last_seen = time.time()

    def resize(self, cols, rows):
        cols = max(10, min(int(cols), 500))
        rows = max(4, min(int(rows), 300))
        try:
            fcntl.ioctl(self._master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        except OSError:
            pass

    def close(self):
        if self.closed:
            return
        for sig, wait in ((signal.SIGHUP, 1.0), (signal.SIGKILL, 1.0)):
            try:
                os.killpg(self.proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            end = time.time() + wait
            while time.time() < end and self.proc.poll() is None:
                time.sleep(0.05)
            if self.proc.poll() is not None:
                return

    def info(self):
        return {'id': self.id, 'user': self.user, 'closed': self.closed, 'exit_code': self.exit_code,
                'offset': self.end, 'start': self._start}


_sessions = {}
_lock = threading.Lock()


def open_session(cols=120, rows=30, sid=None):
    """Reattach to `sid` if it is still alive, else start a new shell."""
    with _lock:
        s = _sessions.get(sid) if sid else None
        if s and not s.closed:
            s.resize(cols, rows)
            s.last_seen = time.time()
            return s, True
        for k in [k for k, v in _sessions.items() if v.closed]:
            del _sessions[k]
        if len(_sessions) >= MAX_SESSIONS:
            raise TermError(f'Too many terminals open (max {MAX_SESSIONS}) — close one', 429)
        s = Session(cols, rows)
        _sessions[s.id] = s
        return s, False


def get(sid):
    s = _sessions.get(sid or '')
    if not s:
        raise TermError('No such terminal', 404)
    return s


def close(sid):
    s = _sessions.pop(sid or '', None)
    if s:
        threading.Thread(target=s.close, daemon=True).start()
    return bool(s)


def _reaper():
    while True:
        time.sleep(10)
        now = time.time()
        with _lock:
            stale = [k for k, s in _sessions.items()
                     if s.closed or (s.readers == 0 and now - s.last_seen > IDLE_SECONDS)]
            for k in stale:
                s = _sessions.pop(k)
                threading.Thread(target=s.close, daemon=True).start()


threading.Thread(target=_reaper, name='term-reaper', daemon=True).start()


def stream(s, offset):
    """Generator of Server-Sent Events: 'out' {d: text, o: next offset}, 'exit' {code}, heartbeats."""
    import json
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    s.readers += 1
    try:
        yield 'retry: 1000\n\n'
        while True:
            data, offset, done = s.read(offset)
            s.last_seen = time.time()
            if data:
                text = decoder.decode(data)
                if text:
                    yield f'event: out\ndata: {json.dumps({"d": text, "o": offset})}\n\n'
            elif not done:
                yield ': ping\n\n'                     # keeps proxies / the browser from timing out
            if done:
                yield f'event: exit\ndata: {json.dumps({"code": s.exit_code})}\n\n'
                return
    finally:
        s.readers -= 1
        s.last_seen = time.time()
