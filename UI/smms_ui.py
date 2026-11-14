"""Helpers for the device display scripts in UI/ (started by the panel: core/display_ui.py, Settings → Display).

Every script starts with

    import smms_ui
    smms_ui.setup()                 # before any other Kivy import: applies the display settings to Kivy
    from kivy.app import App ...

and gets: ``settings()`` (resolution, rotation, cursor, input of Settings → Display), ``api`` (the panel's HTTP API with
the script's token: ``api.get('/api/monitor')``, ``api.post('/api/tests/stop')``), ``poll()`` (background polling with
the callback on the Kivy thread), a colour theme, ``Card`` and ``LineChart`` widgets, ``image()`` (pictures dropped
into UI/images/) and a SIGTERM handler (the panel stops a script with SIGTERM when another one is chosen).

Development: run a script by hand on the board — on the console (no X): ``SDL_VIDEODRIVER=kmsdrm python3 UI/x.py``,
in an X session: ``python3 UI/x.py``. Without SMMS_TOKEN the API works only when the panel's login is off.
"""
import glob
import json
import os
import signal
import threading
import time
import urllib.error
import urllib.request

UI_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES = os.path.join(UI_DIR, 'images')
BACKGROUNDS = os.path.join(UI_DIR, 'backgrounds')     # Settings → Display → Background (one for every script)
DEFAULTS = {'mode': 'auto', 'fullscreen': True, 'width': 0, 'height': 0, 'rotation': 0, 'cursor': 'auto', 'fps': 30,
            'touch': True, 'mouse': True, 'scale': 0, 'background': '', 'bg_dim': 40}
BASE_HEIGHT = 720                 # auto scale: dp / sp grow with the screen (1080p → ×1.5)

# Colours of the panel (static/css/base.css), as Kivy RGBA.
THEME = {
    'bg': (0.067, 0.067, 0.067, 1), 'panel': (0.102, 0.102, 0.102, 1), 'panel2': (0.14, 0.14, 0.14, 1),
    'border': (0.165, 0.165, 0.165, 1), 'text': (0.867, 0.867, 0.867, 1), 'dim': (0.47, 0.47, 0.47, 1),
    'accent': (0.306, 0.788, 0.69, 1), 'info': (0.494, 0.784, 0.961, 1), 'warn': (0.91, 0.659, 0.22, 1),
    'danger': (0.957, 0.278, 0.278, 1), 'ok': (0.306, 0.788, 0.69, 1),
}


def hexcolor(rgba):
    return '%02x%02x%02x' % tuple(int(c * 255) for c in rgba[:3])


def settings():
    """Display settings given by the panel (SMMS_DISPLAY), defaults when the script runs by hand."""
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(os.environ.get('SMMS_DISPLAY') or '{}'))
    except ValueError:
        pass
    return s


def background():
    """Path of the background picture chosen in the settings, None without one."""
    name = settings().get('background') or ''
    p = os.path.join(BACKGROUNDS, os.path.basename(name))
    return p if name and os.path.isfile(p) else None


def _install_background(dt=None):
    """Draw the chosen picture under every widget of the window (Window.canvas.before), darkened by ``bg_dim`` %;
    follows resizing / rotation. Runs on the first frame, so no script has to do anything."""
    path = background()
    if not path:
        return
    from kivy.core.window import Window
    from kivy.graphics import Color, Rectangle
    dim = max(0, min(95, int(settings().get('bg_dim') or 0))) / 100
    with Window.canvas.before:
        Color(1, 1, 1, 1)
        pic = Rectangle(source=path, pos=(0, 0), size=Window.size)
        Color(0, 0, 0, dim)
        shade = Rectangle(pos=(0, 0), size=Window.size)

    def fit(*_):
        pic.size = shade.size = Window.size
    Window.bind(size=fit, rotation=fit)


def has_mouse():
    try:
        with open('/proc/bus/input/devices', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return False
    return any(line.startswith('H: Handlers=') and 'mouse' in line for line in text.splitlines())


def screen_size(s=None):
    """(w, h) of the configured size, else of the connected DRM output (first mode), else None."""
    s = s or settings()
    w, h = int(s.get('width') or 0), int(s.get('height') or 0)
    if w and h:
        return w, h
    for st in sorted(glob.glob('/sys/class/drm/card*-*/status')):
        try:
            with open(st, encoding='utf-8') as f:
                if f.read().strip() != 'connected':
                    continue
            with open(os.path.join(os.path.dirname(st), 'modes'), encoding='utf-8') as f:
                mode = f.readline().strip()
            mw, mh = mode.split('x')[:2]
            return int(mw), int(''.join(c for c in mh if c.isdigit()))
        except (OSError, ValueError):
            continue
    return None


def density(s=None):
    """dp / sp factor: the ``scale`` setting in %, or automatic from the screen height (BASE_HEIGHT = 1)."""
    s = s or settings()
    if int(s.get('scale') or 0):
        return int(s['scale']) / 100
    size = screen_size(s)
    return round(min(3.0, max(0.75, min(size) / BASE_HEIGHT)), 2) if size else 1.0


def die_with_panel():
    """SIGTERM when the panel process dies. The panel sets PR_SET_PDEATHSIG before exec, but the kernel clears it
    when the interpreter has file capabilities (e.g. setcap cap_net_bind_service on python3) — so set it again here
    and leave at once if the panel is already gone."""
    parent = os.environ.get('SMMS_PARENT')
    if not parent:
        return
    try:
        import ctypes
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)       # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass
    if str(os.getppid()) != parent:
        os._exit(0)


def setup(keyboard=False):
    """Apply the settings to Kivy's Config — call before importing kivy.app / kivy.core.window.
    ``keyboard``: show Kivy's on-screen keyboard for text fields (touch screens without a keyboard)."""
    die_with_panel()
    s = settings()
    if background():                              # panels let the background picture show through
        for key, alpha in (('bg', 1), ('panel', 0.78), ('panel2', 0.82)):
            THEME[key] = THEME[key][:3] + (alpha,)
    os.environ.setdefault('KIVY_NO_ARGS', '1')
    os.environ.setdefault('KIVY_HOME', os.path.join(UI_DIR, '.kivy'))
    os.environ.setdefault('KIVY_METRICS_DENSITY', str(density(s)))
    from kivy.config import Config
    kms = s.get('mode') == 'kmsdrm' or os.environ.get('SDL_VIDEODRIVER') == 'kmsdrm'
    w, h = int(s.get('width') or 0), int(s.get('height') or 0)
    if s.get('fullscreen') or kms:              # on DRM/KMS there is no window: always the whole screen
        Config.set('graphics', 'fullscreen', '1' if (w and h) else 'auto')
        Config.set('graphics', 'borderless', '1')
    else:
        Config.set('graphics', 'fullscreen', '0')
        Config.set('graphics', 'borderless', '0')
    if w and h:
        Config.set('graphics', 'width', str(w))
        Config.set('graphics', 'height', str(h))
    Config.set('graphics', 'rotation', str(int(s.get('rotation') or 0)))
    Config.set('graphics', 'maxfps', str(int(s.get('fps') or 30)))
    cursor = s.get('cursor', 'auto')
    show = cursor == 'on' or (cursor == 'auto' and (not kms or has_mouse()))
    if kms and show:
        # SDL draws no pointer on DRM/KMS: Kivy's cursor module draws one (it follows the mouse once it moves)
        px = max(16, int(24 * density(s)))
        Config.set('graphics', 'show_cursor', '0')
        Config.set('modules', 'cursor', f'size={px}x{px}')
    else:
        Config.set('graphics', 'show_cursor', '1' if show else '0')
    Config.set('kivy', 'exit_on_escape', '0')
    Config.set('kivy', 'keyboard_mode', 'systemanddock' if keyboard else 'system')
    # input: SDL gives mouse / keyboard; touch screens are read by Kivy itself (probesysfs → mtdev / hidinput)
    for opt in list(Config.options('input')):
        Config.remove_option('input', opt)
    if s.get('mouse', True):
        Config.set('input', 'mouse', 'mouse,disable_on_activity')
    if s.get('touch', True):
        Config.set('input', '%(name)s', 'probesysfs')
    signal.signal(signal.SIGTERM, _on_term)
    from kivy.clock import Clock
    Clock.schedule_once(_install_background, 0)
    shot = os.environ.get('SMMS_SHOT')          # development / tests: save the screen to a PNG after N s and quit
    if shot:
        from kivy.clock import Clock

        def take(dt):
            from kivy.app import App
            from kivy.core.window import Window
            if os.path.exists(shot):
                os.remove(shot)
            made = Window.screenshot(name=shot)    # Kivy 2.1: the real frame buffer; it adds a counter to the name
            if made and made != shot:
                os.replace(made, shot)
            App.get_running_app().stop()
        Clock.schedule_once(take, float(os.environ.get('SMMS_SHOT_DELAY') or 5))
    return s


def _on_term(*_):
    """The panel replaces / stops the script: close the app cleanly, hard exit if it hangs."""
    threading.Timer(2.5, lambda: os._exit(0)).start()
    try:
        from kivy.app import App
        from kivy.clock import Clock
        app = App.get_running_app()
        if app:
            Clock.schedule_once(lambda dt: app.stop(), 0)
            return
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


def image(name):
    """Path of UI/images/<name> when it exists, else None (scripts draw a fallback)."""
    p = os.path.join(IMAGES, name)
    return p if os.path.isfile(p) else None


# ── Panel API ───────────────────────────────────────────────

class ApiError(Exception):
    pass


class Api:
    def __init__(self):
        self.base = os.environ.get('SMMS_API', 'http://127.0.0.1').rstrip('/')
        self.token = os.environ.get('SMMS_TOKEN', '')

    def call(self, path, body=None, timeout=5):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method='POST' if data is not None else 'GET',
                                     headers={'X-SMMS-Token': self.token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8') or 'null')
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode('utf-8')).get('error') or str(e)
            except (ValueError, AttributeError):
                msg = str(e)
            raise ApiError(msg) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ApiError(f'panel not reachable: {getattr(e, "reason", e)}') from None

    def get(self, path, timeout=5):
        return self.call(path, None, timeout)

    def post(self, path, body=None, timeout=10):
        return self.call(path, body or {}, timeout)


api = Api()


def poll(path, seconds, callback, error=None):
    """GET ``path`` (a string or a function returning one) every ``seconds`` in a thread; ``callback(data)`` /
    ``error(message)`` run on the Kivy thread. Returns a function that stops the polling."""
    from kivy.clock import Clock
    stop = threading.Event()

    def run():
        while not stop.is_set():
            t0 = time.time()
            try:
                d = api.get(path() if callable(path) else path)
                Clock.schedule_once(lambda dt, d=d: callback(d))
            except ApiError as e:
                if error:
                    Clock.schedule_once(lambda dt, m=str(e): error(m))
            stop.wait(max(0.05, seconds - (time.time() - t0)))
    threading.Thread(target=run, name='smms-poll', daemon=True).start()
    return stop.set


def in_background(fn, done=None, error=None):
    """Run ``fn()`` (e.g. an API POST) off the Kivy thread; ``done(result)`` / ``error(message)`` back on it."""
    from kivy.clock import Clock

    def run():
        try:
            r = fn()
            if done:
                Clock.schedule_once(lambda dt: done(r))
        except Exception as e:  # noqa: BLE001
            if error:
                Clock.schedule_once(lambda dt, m=str(e): error(m))
    threading.Thread(target=run, daemon=True).start()


# ── Formatting ──────────────────────────────────────────────

def fmt_bytes(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def fmt_rate(n):
    return fmt_bytes(n) + '/s'


def fmt_uptime(sec):
    sec = int(sec or 0)
    d, h, m = sec // 86400, sec // 3600 % 24, sec // 60 % 60
    return f'{d}d {h}h {m}m' if d else f'{h}h {m}m'


# ── Widgets (imported lazily: Kivy must be configured first) ──

def widgets():
    """Card and LineChart classes (created after setup(), so Kivy reads the configured settings)."""
    global Card, LineChart
    if 'Card' in globals():
        return Card, LineChart
    from kivy.graphics import Color, Line, Rectangle, RoundedRectangle
    from kivy.metrics import dp
    from kivy.properties import ListProperty, NumericProperty
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.widget import Widget

    class _Card(BoxLayout):
        """Rounded panel with the theme background."""
        bg = ListProperty(THEME['panel'])

        def __init__(self, **kw):
            kw.setdefault('padding', dp(10))
            kw.setdefault('spacing', dp(6))
            super().__init__(**kw)
            with self.canvas.before:
                self._c = Color(*self.bg)
                self._r = RoundedRectangle(radius=[dp(8)])
            self.bind(pos=self._upd, size=self._upd, bg=self._upd)

        def _upd(self, *_):
            self._c.rgba = self.bg
            self._r.pos, self._r.size = self.pos, self.size

    class _LineChart(Widget):
        """Time chart: series [{'color', 'points': [(t, v)], 'dash'}]; one y axis (0…ymax or auto), last ``window`` s."""
        ymax = NumericProperty(0)          # 0 = auto
        window = NumericProperty(300)

        def __init__(self, series=(), **kw):
            super().__init__(**kw)
            self.series = [dict(s, points=list(s.get('points', []))) for s in series]
            self.bind(pos=self.redraw, size=self.redraw)

        def push(self, idx, t, v, keep=2000):
            pts = self.series[idx]['points']
            pts.append((t, v))
            if len(pts) > keep:
                del pts[:len(pts) - keep]

        def top(self):
            if self.ymax:
                return self.ymax
            m = max((v for s in self.series for _, v in s['points']), default=1) or 1
            for step in (1, 2, 5):                       # a round number above the data
                for p in range(-1, 12):
                    nice = step * 10 ** p
                    if nice >= m * 1.1:
                        return nice
            return m

        def redraw(self, *_):
            self.canvas.clear()
            x0, y0, w, h = self.x, self.y, max(1, self.width), max(1, self.height)
            now = max((s['points'][-1][0] for s in self.series if s['points']), default=time.time())
            top = self.top()
            with self.canvas:
                Color(*THEME['panel2'])
                Rectangle(pos=self.pos, size=self.size)
                Color(*THEME['border'])
                for i in range(1, 4):
                    Line(points=[x0, y0 + h * i / 4, x0 + w, y0 + h * i / 4], width=1)
                for s in self.series:
                    pts = []
                    for t, v in s['points']:
                        if t < now - self.window:
                            continue
                        pts += [x0 + w * (1 - (now - t) / self.window), y0 + h * min(1.0, max(0.0, v / top))]
                    if len(pts) >= 4:
                        Color(*s['color'])
                        if s.get('dash'):
                            Line(points=pts, width=1, dash_length=6, dash_offset=4)
                        else:
                            Line(points=pts, width=dp(1.3))

    Card, LineChart = _Card, _LineChart
    return Card, LineChart
