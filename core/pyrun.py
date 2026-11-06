"""Run / debug a Python script from the code editor (one session at a time).

The script runs in a pseudo-terminal, so it behaves exactly as in an SSH console (``input()`` echo, line
buffering, Ctrl-C); its output is buffered here and polled by the editor's terminal, typed lines go to the pty.
In debug mode the process runs ``core/pydbg_agent.py`` (a ``bdb`` debugger) which talks to this module over two
pipes (JSON lines): breakpoints, step / continue / pause / stop, and evaluation of variables while paused.

Like the other background resources, a session lives only while the editor polls it (``LEASE_SECONDS``);
every exit path stops the process: Stop, page close (beacon), lease timeout, panel exit (PDEATHSIG).
Stopping is gentle first — the debugger quits at the current line or the script gets SIGINT, so ``finally``
blocks (a test's ``finalize``) still bring the fixture to a safe state — then SIGTERM / SIGKILL.
"""
import fcntl
import itertools
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time

from core import config, spawn
from core.shell import resolve_inside

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
LEASE_SECONDS = 30
MAX_OUTPUT = 2 * 1024 * 1024          # bytes of output kept for the terminal
REPLY_TIMEOUT = 5
STOP_GRACE = (2.0, 2.0)               # seconds after SIGINT / SIGTERM before the next signal


class RunError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


# Set by routes (e.g. "a test script is running") — returns a reason to refuse a start, or None.
blocked = lambda: None   # noqa: E731
# Called right before a session starts (routes release web-held GPIO lines here).
before_start = lambda: None   # noqa: E731


def _child_setup():
    """preexec: own session with the pty as controlling terminal (Ctrl-C, job control)."""
    os.setsid()
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass


class Session:
    _ids = itertools.count(1)

    def __init__(self, path, args, debug, breaks, stop_on_entry):
        self.id = next(self._ids)
        self.path, self.args, self.debug = path, args, debug
        self.state = 'starting'        # running | paused | exited
        self.exit_code = None
        self.paused = None             # last "paused" event
        self.exception = None
        self.started = time.time()
        self.last_poll = time.time()
        self._out = []                 # [(seq, text)]
        self._out_bytes = 0
        self._seq = 0
        self._lock = threading.Lock()
        self._replies = {}
        self._reply_ids = itertools.count(1)
        self._cmd_w = None
        self._stopping = False

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 120, 0, 0))
        self._master = master
        env = dict(os.environ, PYTHONUNBUFFERED='1', TERM='xterm-256color', COLUMNS='120', LINES='30')
        env.pop('TEST_RUNNER', None)
        pass_fds = ()
        if debug:
            cmd_r, cmd_w = os.pipe()
            ev_r, ev_w = os.pipe()
            env.update(SMMS_DBG_FDS=f'{cmd_r},{ev_w}', SMMS_DBG_ENTRY='1' if stop_on_entry else '',
                       SMMS_DBG_BREAKS=json.dumps(breaks),
                       SMMS_DBG_ROOTS=os.pathsep.join([os.path.realpath(config.target_dir())]))
            boot = (f'import sys; sys.path.insert(0, {AGENT_DIR!r}); import pydbg_agent; pydbg_agent.main()')
            argv = [sys.executable, '-u', '-c', boot, path, *args]
            pass_fds = (cmd_r, ev_w)
        else:
            argv = [sys.executable, '-u', path, *args]
        try:
            # spawn.popen: forked from a long-lived thread, so PDEATHSIG fires only when the panel exits
            self.proc = spawn.popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=os.path.dirname(path),
                                    env=env, pass_fds=pass_fds, setup=_child_setup, close_fds=True)
        except OSError as e:
            os.close(master)
            os.close(slave)
            raise RunError(f'Cannot start Python: {e}', 500)
        finally:
            if debug:
                os.close(cmd_r)
                os.close(ev_w)
        os.close(slave)
        if debug:
            self._cmd_w = os.fdopen(cmd_w, 'w', encoding='utf-8')
            threading.Thread(target=self._events, args=(ev_r,), name='pyrun-events', daemon=True).start()
        self.state = 'running'
        threading.Thread(target=self._pump, name='pyrun-output', daemon=True).start()

    # ── output ──
    def _add(self, text):
        with self._lock:
            self._seq += 1
            self._out.append((self._seq, text))
            self._out_bytes += len(text)
            while self._out_bytes > MAX_OUTPUT and len(self._out) > 1:
                self._out_bytes -= len(self._out.pop(0)[1])

    def _pump(self):
        while True:
            try:
                r, _, _ = select.select([self._master], [], [], 1.0)
            except (OSError, ValueError):
                break
            if not r:
                if self.proc.poll() is not None:
                    break
                continue
            try:
                data = os.read(self._master, 65536)
            except OSError:          # EIO: the child closed the pty
                break
            if not data:
                break
            self._add(data.decode('utf-8', errors='replace'))
        code = self.proc.wait()
        self.exit_code = code if code >= 0 else 128 - code
        self.state = 'exited'
        self.paused = None
        try:
            os.close(self._master)
        except OSError:
            pass
        if self._cmd_w:
            try:
                self._cmd_w.close()
            except OSError:
                pass
        with self._lock:
            for ev in self._replies.values():
                ev['error'] = 'The program has exited'
                ev['event'].set()

    def _events(self, fd):
        with os.fdopen(fd, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                kind = ev.get('ev')
                if kind == 'paused':
                    self.paused = ev
                    self.state = 'paused'
                elif kind == 'running':
                    self.paused = None
                    if self.state != 'exited':
                        self.state = 'running'
                elif kind == 'exception':
                    self.exception = ev.get('text')
                elif kind == 'reply':
                    with self._lock:
                        waiter = self._replies.get(ev.get('id'))
                    if waiter:
                        waiter['reply'] = ev
                        waiter['event'].set()

    def output(self, since):
        with self._lock:
            chunks = [t for s, t in self._out if s > since]
            first = self._out[0][0] if self._out else self._seq + 1
            return ''.join(chunks), self._seq, since and since + 1 < first

    # ── control ──
    def _send(self, msg):
        if not self._cmd_w:
            raise RunError('Not a debug session', 409)
        try:
            self._cmd_w.write(json.dumps(msg) + '\n')
            self._cmd_w.flush()
        except (BrokenPipeError, ValueError, OSError):
            raise RunError('The debugger is gone', 409)

    def request(self, msg):
        rid = next(self._reply_ids)
        waiter = {'event': threading.Event(), 'reply': None, 'error': None}
        with self._lock:
            self._replies[rid] = waiter
        try:
            self._send(dict(msg, id=rid))
            if not waiter['event'].wait(REPLY_TIMEOUT):
                raise RunError('The debugger did not answer', 504)
            if waiter['error']:
                raise RunError(waiter['error'], 409)
            return waiter['reply']
        finally:
            with self._lock:
                self._replies.pop(rid, None)

    def command(self, action):
        if self.state == 'exited':
            raise RunError('The program has exited', 409)
        if action == 'pause':
            if self.state != 'running':
                raise RunError('Not running', 409)
            self._send({'cmd': 'pause'})
            return
        if self.state != 'paused':
            raise RunError('The program is not paused', 409)
        self._send({'cmd': action})
        self.paused = None
        self.state = 'running'

    def write(self, text):
        if self.state == 'exited':
            raise RunError('The program has exited', 409)
        data = text.encode('utf-8')
        while data:
            n = os.write(self._master, data)
            data = data[n:]

    def stop(self):
        """Gentle stop in a background thread: quit the debugger / SIGINT, then SIGTERM, then SIGKILL."""
        if self.state == 'exited' or self._stopping:
            return
        self._stopping = True

        def run():
            was_paused = self.state == 'paused'
            if self.debug:
                try:
                    self._send({'cmd': 'stop'})       # quit at the current / next line (finally blocks run)
                except RunError:
                    pass
            if not was_paused:
                time.sleep(0.3 if self.debug else 0)
                if self.proc.poll() is None:
                    self._signal(signal.SIGINT)        # blocked in sleep / input(): KeyboardInterrupt
            for sig, wait in ((signal.SIGTERM, STOP_GRACE[0]), (signal.SIGKILL, STOP_GRACE[1])):
                deadline = time.time() + wait
                while time.time() < deadline and self.proc.poll() is None:
                    time.sleep(0.05)
                if self.proc.poll() is not None:
                    return
                self._signal(sig)
        threading.Thread(target=run, name='pyrun-stop', daemon=True).start()

    def _signal(self, sig):
        try:
            os.killpg(self.proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def snapshot(self, since=0):
        text, seq, lost = self.output(since)
        return {'id': self.id, 'path': self.path, 'args': self.args, 'debug': self.debug, 'state': self.state,
                'exit_code': self.exit_code, 'paused': self.paused, 'exception': self.exception,
                'output': text, 'seq': seq, 'lost': bool(lost), 'started': self.started}


_session = None
_glock = threading.Lock()


def _reaper():
    while True:
        time.sleep(5)
        s = _session
        if s and s.state != 'exited' and time.time() - s.last_poll > LEASE_SECONDS:
            s._add('\r\n[stopped: the editor stopped polling this session]\r\n')
            s.stop()


threading.Thread(target=_reaper, name='pyrun-lease', daemon=True).start()


def current():
    return _session


def active():
    """True while a run / debug session has a live process (tests must not start then)."""
    return bool(_session and _session.state != 'exited')


def check_script(path):
    real = resolve_inside(path or '', config.target_dir())
    if not real or not real.endswith('.py'):
        raise RunError('Only .py files inside target_dir can be run', 403)
    if not os.path.isfile(real):
        raise RunError('File not found', 404)
    return real


def _clean_breaks(breaks):
    out = {}
    if not isinstance(breaks, dict):
        return out
    root = config.target_dir()
    for f, lines in list(breaks.items())[:200]:
        real = resolve_inside(f, root)
        if real and isinstance(lines, list):
            out[real] = sorted({int(n) for n in lines if isinstance(n, int) and 0 < n < 10 ** 7})[:500]
    return out


def start(path, args=(), debug=False, breaks=None, stop_on_entry=False):
    global _session
    real = check_script(path)
    if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args) or len(args) > 64:
        raise RunError('Bad arguments')
    why = blocked()
    if why:
        raise RunError(why, 409)
    with _glock:
        if active():
            raise RunError('A program is already running — stop it first', 409)
        before_start()
        _session = Session(real, list(args), bool(debug), _clean_breaks(breaks or {}), bool(stop_on_entry))
        return _session


def get(sid):
    s = _session
    if not s or (sid is not None and str(s.id) != str(sid)):
        raise RunError('No such session', 404)
    s.last_poll = time.time()
    return s


def set_breaks(breaks):
    s = _session
    clean = _clean_breaks(breaks)
    if s and s.debug and s.state != 'exited':
        s.request({'cmd': 'breaks', 'breaks': clean})
    return clean
