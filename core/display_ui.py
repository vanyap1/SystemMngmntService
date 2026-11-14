"""Device display UI (Settings → Display): one Kivy script from UI/ drawn on the board's own screen.

The script runs as a separate process (the owner of the project, with its video / render / input groups) started by a
supervisor thread of the panel: it starts the configured script when the feature is enabled, replaces it when the
settings change (old one stopped: SIGTERM to its group, SIGKILL after STOP_SECONDS), restarts it after a crash with a
growing delay (BACKOFF) and stops it when the feature is switched off. The child dies with the panel (spawn.popen).

Output: ``auto`` = into the X server when one runs on ``x_display`` (a window, or full screen), otherwise directly on
the display through DRM/KMS (SDL ``kmsdrm`` — the console login prompt is replaced while the script runs).

Scripts read the panel through its HTTP API: SMMS_API + SMMS_TOKEN in their environment; the token is accepted only
from the loopback interface and only while that process runs (core.auth.is_logged_in). UI/smms_ui.py applies the
settings (SMMS_DISPLAY) to Kivy and gives the scripts an API client, charts and the SIGTERM handling.
"""
import ast
import collections
import glob
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time

from core import config, spawn

SCRIPT = re.compile(r'^[A-Za-z0-9][\w.-]{0,80}\.py$')
LIBRARY = ('smms_ui.py', 'screen_runner.py')   # helpers in UI/, not offered as scripts
SCREEN = re.compile(r'^screens/([A-Za-z0-9][\w-]{0,39})\.json$')   # a designer screen, run by UI/screen_runner.py
MODES = ('auto', 'kmsdrm', 'x11')
ROTATIONS = (0, 90, 180, 270)
CURSORS = ('auto', 'on', 'off')
DEFAULTS = {'enabled': False, 'script': 'system_monitor.py', 'mode': 'auto', 'x_display': ':0', 'fullscreen': True,
            'width': 0, 'height': 0, 'rotation': 0, 'cursor': 'auto', 'fps': 30, 'touch': True, 'mouse': True,
            'scale': 0, 'background': '', 'bg_dim': 40}
BACKGROUND = re.compile(r'^[\w.() -]{1,100}\.(png|jpe?g)$', re.I)    # a file in UI/backgrounds/
STOP_SECONDS = 4
BACKOFF = (2, 5, 10, 30, 60)           # restart delays after crashes in a row (a run over STABLE_SECONDS resets it)
STABLE_SECONDS = 60
LOG_LINES = 300
TICK = 1.0
_ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
_RENDERER = re.compile(r"OpenGL renderer <b?'?(.+?)'?>")
SOFT_GL = re.compile(r'llvmpipe|softpipe|swrast|software', re.I)
SOFT_DRM = ('vgem', 'vkms')                 # render nodes without a GPU behind them


class DisplayError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def ui_dir():
    return os.path.join(config.BASE_DIR, 'UI')


# ── Settings ────────────────────────────────────────────────

def settings():
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (config.get('display') or {}).items() if k in DEFAULTS})
    return s


def check(data):
    """Client settings -> clean dict (unknown keys dropped, values validated)."""
    data = data if isinstance(data, dict) else {}
    s = settings()

    def num(key, lo, hi):
        try:
            v = int(data.get(key, s[key]))
        except (TypeError, ValueError):
            raise DisplayError(f'{key}: a whole number')
        if not lo <= v <= hi:
            raise DisplayError(f'{key}: {lo}…{hi}')
        return v
    out = {
        'enabled': bool(data.get('enabled', s['enabled'])),
        'script': str(data.get('script', s['script']) or ''),
        'mode': str(data.get('mode', s['mode'])),
        'x_display': str(data.get('x_display', s['x_display']) or ':0').strip(),
        'fullscreen': bool(data.get('fullscreen', s['fullscreen'])),
        'width': num('width', 0, 8192), 'height': num('height', 0, 8192),
        'rotation': num('rotation', 0, 270), 'fps': num('fps', 1, 120), 'scale': num('scale', 0, 400),
        'cursor': str(data.get('cursor', s['cursor'])),
        'touch': bool(data.get('touch', s['touch'])), 'mouse': bool(data.get('mouse', s['mouse'])),
        'background': str(data.get('background', s['background']) or ''), 'bg_dim': num('bg_dim', 0, 95),
    }
    if out['background'] and not BACKGROUND.match(out['background']):
        raise DisplayError('Background: a .png / .jpg file name in UI/backgrounds/')
    if out['script'] and not SCREEN.match(out['script']) and (not SCRIPT.match(out['script']) or out['script'] in LIBRARY):
        raise DisplayError('Script: a .py file name in UI/ or screens/<name>.json')
    if out['mode'] not in MODES:
        raise DisplayError('Mode: ' + ', '.join(MODES))
    if out['rotation'] not in ROTATIONS:
        raise DisplayError('Rotation: 0, 90, 180 or 270')
    if out['cursor'] not in CURSORS:
        raise DisplayError('Cursor: ' + ', '.join(CURSORS))
    if not re.match(r'^:\d{1,2}(\.\d)?$', out['x_display']):
        raise DisplayError('X display: like :0')
    return out


def save(data):
    s = check(data)
    if s['enabled'] and s['script'] not in {x['name'] for x in scripts()}:
        raise DisplayError(f'No script {s["script"]} in UI/', 404)
    if s['background'] and not background_path(s['background']):
        raise DisplayError(f'No picture {s["background"]} in UI/backgrounds/', 404)
    config.save_key('display', s)
    supervisor.kick()
    return s


# ── Environment ─────────────────────────────────────────────

def _doc(path):
    try:
        with open(path, encoding='utf-8') as f:
            doc = ast.get_docstring(ast.parse(f.read())) or ''
    except (OSError, SyntaxError, ValueError):
        return ''
    return doc.strip().splitlines()[0] if doc.strip() else ''


def scripts():
    """UI/*.py that can be shown: [{name, description}] (helpers and _private files left out)."""
    try:
        names = sorted(n for n in os.listdir(ui_dir()) if n.endswith('.py') and SCRIPT.match(n)
                       and n not in LIBRARY and not n.startswith('_'))
    except OSError:
        return []
    from core import ui_screens
    return [{'name': n, 'description': _doc(os.path.join(ui_dir(), n))} for n in names] + \
        [{'name': f'screens/{s["name"]}.json', 'description': f'Designer screen: {s["title"] or s["name"]} '
          f'({s["widgets"]} widgets) — page UI'} for s in ui_screens.list_screens()]


def command(script):
    """argv + extra env of a script: a .py directly, a designer screen through UI/screen_runner.py."""
    m = SCREEN.match(script)
    if m:
        return [sys.executable, '-u', os.path.join(ui_dir(), 'screen_runner.py')], {'SMMS_SCREEN': m.group(1)}
    return [sys.executable, '-u', os.path.join(ui_dir(), script)], {}


def backgrounds_dir():
    return os.path.join(ui_dir(), 'backgrounds')


def backgrounds():
    """Pictures in UI/backgrounds/ for the background of every display script: [{name, size}]."""
    try:
        names = sorted(n for n in os.listdir(backgrounds_dir()) if BACKGROUND.match(n))
    except OSError:
        return []
    return [{'name': n, 'size': os.path.getsize(os.path.join(backgrounds_dir(), n))} for n in names]


def background_path(name):
    """Full path of a background picture, None when the name is not one (no paths, only that folder)."""
    if not BACKGROUND.match(name or '') or '/' in name:
        return None
    p = os.path.join(backgrounds_dir(), name)
    return p if os.path.isfile(p) else None


def _driver(sysdir):
    try:
        return os.path.basename(os.path.realpath(os.path.join(sysdir, 'device', 'driver')))
    except OSError:
        return ''


def gpu_info(renderer=None, sys_drm='/sys/class/drm'):
    """GPU acceleration for the display: render nodes with their kernel driver, connected outputs and — once a
    script has run — the OpenGL renderer Kivy reported. ``hw`` False = Kivy draws on the CPU (slow)."""
    nodes = [{'node': '/dev/dri/' + os.path.basename(p), 'driver': _driver(p)}
             for p in sorted(glob.glob(os.path.join(sys_drm, 'renderD*')))]
    outputs = []
    for p in sorted(glob.glob(os.path.join(sys_drm, 'card*-*'))):
        try:
            with open(os.path.join(p, 'status'), encoding='utf-8') as f:
                status = f.read().strip()
            with open(os.path.join(p, 'modes'), encoding='utf-8') as f:
                mode = f.readline().strip()
        except OSError:
            continue
        outputs.append({'name': os.path.basename(p).split('-', 1)[1], 'status': status, 'mode': mode,
                        'driver': _driver(os.path.dirname(os.path.realpath(p)))})
    gpu_nodes = [n for n in nodes if n['driver'] and n['driver'] not in SOFT_DRM]
    software = bool(renderer and SOFT_GL.search(renderer))
    return {'nodes': nodes, 'outputs': outputs, 'renderer': renderer or None, 'software': software,
            'hw': bool(gpu_nodes) and not software}


_kivy = {'checked': 0.0, 'version': None}


def kivy_version():
    """Installed Kivy version (cached a minute; the panel never imports Kivy itself), None = not installed."""
    if time.time() - _kivy['checked'] > 60:
        ver = None
        try:
            from importlib import metadata, util
            if util.find_spec('kivy'):
                try:
                    ver = metadata.version('Kivy')
                except metadata.PackageNotFoundError:
                    ver = 'installed'
        except (ImportError, ValueError):
            ver = None
        _kivy.update(checked=time.time(), version=ver)
    return _kivy['version']


def x_running(display=':0'):
    n = display.lstrip(':').split('.')[0]
    return os.path.exists(f'/tmp/.X11-unix/X{n}')


def resolve_mode(s):
    if s['mode'] != 'auto':
        return s['mode']
    return 'x11' if x_running(s['x_display']) else 'kmsdrm'


def run_user():
    """pwd entry the script runs as: the owner of the project when the panel is root, else the panel's user."""
    if os.geteuid() != 0:
        return pwd.getpwuid(os.geteuid())
    try:
        return pwd.getpwuid(os.stat(config.BASE_DIR).st_uid)
    except (OSError, KeyError):
        return pwd.getpwuid(0)


def _xauthority(user, display):
    """An X cookie file the script's user can read: its own ~/.Xauthority, or a copy of the display manager's."""
    own = os.path.join(user.pw_dir, '.Xauthority')
    if os.path.isfile(own):
        return own
    for src in (f'/var/run/lightdm/root/{display}', f'/run/lightdm/root/{display}'):
        if os.path.isfile(src) and os.access(src, os.R_OK):
            run = os.path.join(ui_dir(), '.run')
            os.makedirs(run, exist_ok=True)
            dst = os.path.join(run, 'xauthority')
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o600)
            if os.geteuid() == 0:
                os.chown(run, user.pw_uid, user.pw_gid)
                os.chown(dst, user.pw_uid, user.pw_gid)
            return dst
    return ''


def _video_urls():
    from core import video_sources
    return video_sources.urls()


def child_env(s, mode, user, token):
    port = config.get('port', 80)
    env = {
        'HOME': user.pw_dir, 'USER': user.pw_name, 'LOGNAME': user.pw_name,
        'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
        'LANG': os.environ.get('LANG') or 'C.UTF-8',
        'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'KIVY_NO_ARGS': '1', 'KIVY_HOME': os.path.join(ui_dir(), '.kivy'),
        'SMMS_API': f'http://127.0.0.1:{port}', 'SMMS_TOKEN': token, 'SMMS_UI_DIR': ui_dir(),
        'SMMS_DISPLAY': json.dumps(dict(s, mode=mode)),
        'SMMS_PARENT': str(os.getpid()),        # smms_ui.die_with_panel(): PDEATHSIG again after exec
        'SMMS_VIDEO_SOURCES': json.dumps(_video_urls()),   # camera widget: net:<name> → URL with the login
    }
    if mode == 'x11':
        env.update(DISPLAY=s['x_display'], SDL_VIDEODRIVER='x11')
        xa = _xauthority(user, s['x_display'])
        if xa:
            env['XAUTHORITY'] = xa
    else:
        env['SDL_VIDEODRIVER'] = 'kmsdrm'
    return env


# ── Supervisor ──────────────────────────────────────────────

class Supervisor:
    def __init__(self):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.thread = None
        self.proc = None
        self.key = None                 # (script, settings json) of the running process
        self.token = None
        self.started = None
        self.mode = None
        self.script = None
        self.log = collections.deque(maxlen=LOG_LINES)
        self.spawns = 0
        self.fails = 0                  # crashes in a row
        self.next_start = 0.0
        self.last_exit = None           # {code, at, ran, script}
        self.error = ''
        self.renderer = None            # OpenGL renderer of the last script (from Kivy's log)

    # control
    def start(self):
        """Start the supervisor thread (once, from the panel's main process — never in tests / devserver)."""
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._loop, name='display-ui', daemon=True)
            self.thread.start()

    def kick(self):
        with self.lock:
            self.next_start = 0.0
            self.fails = 0
        self.wake.set()

    def restart(self):
        with self.lock:
            self._stop('restart requested')
        self.kick()

    def check_token(self, token):
        with self.lock:
            return bool(self.token and self.proc and self.proc.poll() is None
                        and secrets.compare_digest(str(token), self.token))

    def _note(self, text):
        self.log.append(f'{time.strftime("%H:%M:%S")} [panel] {text}')

    def _desired(self):
        s = settings()
        if not s['enabled']:
            return None, s, ''
        if not kivy_version():
            return None, s, 'Kivy is not installed — install.sh → "display" (python3-kivy)'
        path = os.path.join(ui_dir(), s['script'])
        if not s['script'] or not os.path.isfile(path):
            return None, s, f'Script UI/{s["script"]} not found'
        if SCREEN.match(s['script']) and not os.path.isfile(os.path.join(ui_dir(), 'screen_runner.py')):
            return None, s, 'UI/screen_runner.py is missing'
        mode = resolve_mode(s)
        # changed network cameras restart the script as well (their URLs are in its environment)
        video = hashlib.sha1(json.dumps(_video_urls(), sort_keys=True).encode()).hexdigest()
        return (s['script'], mode, json.dumps(s, sort_keys=True), video), s, ''

    def _loop(self):
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 - the supervisor must keep running
                self.error = f'supervisor: {e}'
            self.wake.wait(TICK)
            self.wake.clear()

    def tick(self):
        with self.lock:
            want, s, err = self._desired()
            self.error = err
            if self.proc and self.proc.poll() is not None:
                self._exited()
            if self.proc and want != self.key:
                self._stop('settings changed' if want else 'display UI switched off')
            if want and not self.proc and time.time() >= self.next_start:
                self._spawn(want, s)

    def _exited(self):
        code, ran = self.proc.returncode, time.time() - (self.started or time.time())
        self.last_exit = {'code': code, 'at': time.time(), 'ran': round(ran, 1), 'script': self.script}
        self._note(f'{self.script} exited with code {code} after {ran:.0f} s')
        self.fails = 0 if ran > STABLE_SECONDS else self.fails + 1
        delay = BACKOFF[min(self.fails, len(BACKOFF)) - 1] if self.fails else BACKOFF[0]
        self.next_start = time.time() + delay
        self._note(f'restart in {delay} s')
        self.proc = self.key = self.token = None

    def _spawn(self, want, s):
        script, mode = want[0], want[1]
        user = run_user()
        token = secrets.token_hex(16)
        env = child_env(s, mode, user, token)
        argv, extra = command(script)
        env.update(extra)
        kw = {}
        if os.geteuid() == 0 and user.pw_uid != 0:
            kw = {'user': user.pw_uid, 'group': user.pw_gid, 'extra_groups': os.getgrouplist(user.pw_name, user.pw_gid)}
        self._note(f'start {script} ({mode}{", " + s["x_display"] if mode == "x11" else ""}) as {user.pw_name}')
        try:
            proc = spawn.popen(argv, cwd=ui_dir(), env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, close_fds=True, **kw)
        except OSError as e:
            self.error = f'Cannot start {script}: {e}'
            self._note(self.error)
            self.fails += 1
            self.next_start = time.time() + BACKOFF[min(self.fails, len(BACKOFF)) - 1]
            return
        self.proc, self.key, self.token = proc, want, token
        self.started, self.mode, self.script = time.time(), mode, script
        self.spawns += 1
        threading.Thread(target=self._read, args=(proc,), name='display-ui-log', daemon=True).start()

    def _read(self, proc):
        for raw in iter(proc.stdout.readline, b''):
            line = _ANSI.sub('', raw.decode('utf-8', 'replace').rstrip())
            if line:
                self.log.append(line[:500])
                m = _RENDERER.search(line)
                if m:
                    self.renderer = m.group(1)
        proc.stdout.close()

    def _stop(self, why):
        proc = self.proc
        if not proc:
            return
        self._note(f'stop {self.script}: {why}')
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(STOP_SECONDS)
        except subprocess.TimeoutExpired:
            self._note('no exit after SIGTERM — SIGKILL')
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.wait(3)
            except subprocess.TimeoutExpired:
                pass
        self.last_exit = {'code': proc.returncode, 'at': time.time(),
                          'ran': round(time.time() - (self.started or time.time()), 1), 'script': self.script}
        self.proc = self.key = self.token = None
        self.next_start = 0.0

    def stop_all(self):
        with self.lock:
            self._stop('panel stops')

    def status(self):
        with self.lock:
            s = settings()
            running = bool(self.proc and self.proc.poll() is None)
            want, _, err = self._desired()
            if not s['enabled']:
                state = 'off'
            elif running:
                state = 'running'
            elif err:
                state = 'error'
            else:
                state = 'waiting'
            log = list(self.log)
            return {
                'settings': s, 'state': state, 'error': err or self.error,
                'pid': self.proc.pid if running else None, 'script': self.script if running else None,
                'mode': self.mode if running else (want[1] if want else resolve_mode(s)),
                'uptime': round(time.time() - self.started, 1) if running and self.started else None,
                'restarts': max(0, self.spawns - 1), 'last_exit': self.last_exit,
                'next_start_in': max(0, round(self.next_start - time.time(), 1)) if not running and want else None,
                'kivy': kivy_version(), 'x_running': x_running(s['x_display']), 'supervisor': bool(self.thread),
                'user': run_user().pw_name, 'log': log[-LOG_LINES:], 'gpu': gpu_info(self.renderer),
            }


supervisor = Supervisor()


def check_token(token):
    return supervisor.check_token(token)
