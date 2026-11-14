"""Designer screen runner: shows UI/screens/<SMMS_SCREEN>.json made on the panel's UI page; reloads it when saved.

Run by the panel for the display script ``screens/<name>.json`` (core/display_ui.command); by hand:
``SMMS_SCREEN=<name> python3 UI/screen_runner.py``. The screen is in design pixels (top-left origin) and is scaled
to the real window; values come from the panel's API (see core/ui_screens.SOURCES), buttons run their actions.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import smms_ui
smms_ui.setup(keyboard=True)

from kivy.app import App                                   # noqa: E402  (after setup)
from kivy.clock import Clock                               # noqa: E402
from kivy.core.window import Window                        # noqa: E402
from kivy.graphics import Color, Line, Rectangle, RoundedRectangle   # noqa: E402
from kivy.graphics.texture import Texture                  # noqa: E402
from kivy.uix.button import Button                         # noqa: E402
from kivy.uix.floatlayout import FloatLayout               # noqa: E402
from kivy.uix.image import Image                           # noqa: E402
from kivy.uix.label import Label                           # noqa: E402
from kivy.uix.widget import Widget                         # noqa: E402

T = smms_ui.THEME
_, LineChart = smms_ui.widgets()
SCREENS = os.path.join(smms_ui.UI_DIR, 'screens')
SOURCES = {'monitor': '/api/monitor', 'tests': '/api/tests/status?results_from=999999&output_from=999999999'}


def color(v, alpha=None):
    """Theme key or #rrggbb -> RGBA."""
    if isinstance(v, str) and v.startswith('#') and len(v) == 7:
        c = tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)) + (1,)
    else:
        c = T.get(v, T['text'])
    return c[:3] + (alpha,) if alpha is not None else c


def get_path(data, path):
    cur = data
    for part in (path or '').split('.'):
        if part == '':
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
        if cur is None:
            return None
    return cur


def fmt(v, kind):
    """Same formats as static/js/uidesign.js fmtValue()."""
    if v is None:
        return '—'
    if isinstance(v, (list, dict)):
        return json.dumps(v)[:60]
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    return {'raw': lambda: str(v), 'int': lambda: f'{n:.0f}', '1dp': lambda: f'{n:.1f}', '2dp': lambda: f'{n:.2f}',
            'percent': lambda: f'{n:.0f} %', 'bytes': lambda: smms_ui.fmt_bytes(n), 'rate': lambda: smms_ui.fmt_rate(n),
            'uptime': lambda: smms_ui.fmt_uptime(n)}.get(kind, lambda: str(v))()


def number(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


class Panel(Widget):
    def __init__(self, spec, **kw):
        super().__init__(**kw)
        with self.canvas:
            Color(*color(spec['color']))
            self.r = RoundedRectangle(radius=[spec['radius']])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self.r.pos, self.r.size = self.pos, self.size


class Bar(Widget):
    """Track + fill in the widget's colour (Kivy's ProgressBar has a fixed look)."""
    def __init__(self, spec, **kw):
        super().__init__(**kw)
        self.max, self.value = spec['max'] or 100, 0
        with self.canvas:
            Color(*T['border'])
            self.track = RoundedRectangle(radius=[4])
            Color(*color(spec['color']))
            self.fill = RoundedRectangle(radius=[4])
        self.bind(pos=self._u, size=self._u)

    def set(self, v):
        self.value = max(0, min(self.max, v))
        self._u()

    def _u(self, *_):
        h = max(4, self.height * 0.12)
        y = self.y + (self.height - h) / 2
        self.track.pos, self.track.size = (self.x, y), (self.width, h)
        self.fill.pos, self.fill.size = (self.x, y), (self.width * self.value / self.max, h)


class CameraReader(threading.Thread):
    """Frames of a V4L2 camera in a thread: OpenCV (MJPG, chosen size / fps) or else ffmpeg (raw RGB on a pipe).
    Only the newest frame is kept; reconnects every 3 s when the device is missing or busy."""
    def __init__(self, device, size, fps):
        super().__init__(name='camera', daemon=True)
        self.device, self.fps = device, fps
        self.net = None                   # {url, transport} of a network source net:<name> (Settings → Video)
        if device.startswith('net:'):
            try:
                self.net = json.loads(os.environ.get('SMMS_VIDEO_SOURCES') or '{}').get(device[4:])
            except ValueError:
                self.net = None
        self.w, self.h = (int(x) for x in size.split('x'))
        self.frame = None                 # (bytes, w, h, colorfmt)
        self.error = ''
        self.stop_ev = threading.Event()
        self.proc = None

    def stop(self):
        self.stop_ev.set()
        if self.proc:
            try:
                self.proc.kill()
            except OSError:
                pass

    def run(self):
        while not self.stop_ev.is_set():
            if self.device.startswith('net:') and not self.net:
                self.error = f'{self.device}: no such video source (Settings, tab Video)'
                self.stop_ev.wait(3)
                continue
            try:
                import cv2                           # noqa: F401
                self._opencv()
            except ImportError:
                self._ffmpeg()
            except Exception as e:  # noqa: BLE001
                self.error = f'{self.device}: {e}'
            self.stop_ev.wait(3)

    def _opencv(self):
        import cv2
        if self.net:
            os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = f'rtsp_transport;{self.net.get("transport", "tcp")}'
            cap = cv2.VideoCapture(self.net['url'], cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            self.error = f'{self.device}: cannot open' + (' (no answer / wrong login)' if self.net else
                                                         ' (missing, or used by another program)')
            return
        try:
            if not self.net:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.h)
                cap.set(cv2.CAP_PROP_FPS, self.fps)
            last = 0.0
            fails = 0
            while not self.stop_ev.is_set():
                ok, img = cap.read()
                if not ok:
                    fails += 1
                    if fails > 20:
                        self.error = f'{self.device}: no frames'
                        return
                    time.sleep(0.05)
                    continue
                fails, self.error = 0, ''
                if self.net:                 # a stream runs at its own rate: keep up, show at most fps
                    now = time.time()
                    if now - last < 1 / self.fps:
                        continue
                    last = now
                    if img.shape[1] > self.w or img.shape[0] > self.h:   # down to the chosen size
                        k = min(self.w / img.shape[1], self.h / img.shape[0])
                        img = cv2.resize(img, (int(img.shape[1] * k), int(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
                h, w = img.shape[:2]
                self.frame = (img.tobytes(), w, h, 'bgr')
        finally:
            cap.release()

    def _ffmpeg(self):
        if not shutil.which('ffmpeg'):
            self.error = 'no OpenCV (python3-opencv) and no ffmpeg — cannot read the camera'
            return
        if self.net:                         # scaled to exactly the chosen size (the reader needs a fixed frame)
            src = (['-rtsp_transport', self.net.get('transport', 'tcp')] if self.net['url'].startswith('rtsp') else []) + \
                ['-i', self.net['url'], '-vf', f'scale={self.w}:{self.h}', '-r', str(self.fps)]
        else:
            src = ['-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', f'{self.w}x{self.h}',
                   '-framerate', str(self.fps), '-i', self.device]
        cmd = ['ffmpeg', '-loglevel', 'error'] + src + ['-an', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        n = self.w * self.h * 3
        try:
            while not self.stop_ev.is_set():
                buf = self.proc.stdout.read(n)
                if len(buf) < n:
                    err = self.proc.stderr.read().decode('utf-8', 'replace').strip().splitlines()
                    msg = err[-1] if err else 'ffmpeg stopped'
                    if self.net:
                        msg = msg.replace(self.net['url'], self.device)
                    self.error = f'{self.device}: {msg}'
                    return
                self.error = ''
                self.frame = (buf, self.w, self.h, 'rgb')
        finally:
            self.proc.kill()
            self.proc.wait()


class Camera(Widget):
    """Video of a camera in a frame (border colour / width / radius), fitted (cover / contain / stretch), mirrored
    or upside down on request, with an optional caption."""
    def __init__(self, spec, **kw):
        super().__init__(**kw)
        self.spec, self.tex, self.shown = spec, None, None
        bw = spec['border_w']
        with self.canvas:
            Color(*T['bg'])
            self.back = RoundedRectangle(radius=[spec['radius']])
            Color(1, 1, 1, 1)
            self.video = Rectangle()
            if bw:
                Color(*color(spec['border']))
                self.frame = Line(width=max(1, bw / 2))
            else:
                self.frame = None
        self.msg = text_label({'color': 'dim', 'align': 'center'}, f'camera {spec["device"]}…')
        self.cap = text_label({'color': 'text', 'align': 'center'}, spec['caption'])
        self.cap.outline_width, self.cap.outline_color = 2, (0, 0, 0, 1)     # readable on any picture
        self.add_widget(self.msg)
        self.add_widget(self.cap)
        self.reader = CameraReader(spec['device'], spec['resolution'], spec['fps'])
        self.reader.start()
        self.ev = Clock.schedule_interval(self.update, 1 / max(1, spec['fps']))
        self.bind(pos=self._layout, size=self._layout)

    def stop(self, wait=0.0):
        self.ev.cancel()
        self.reader.stop()
        if wait:
            self.reader.join(wait)            # the device is released (cap.release) before the process ends

    def update(self, dt):
        f = self.reader.frame
        if f is None or f is self.shown:
            self.msg.text = self.reader.error or self.msg.text
            return
        buf, w, h, fmt_ = f
        if not self.tex or self.tex.size != (w, h):
            self.tex = Texture.create(size=(w, h), colorfmt='rgb')
            self.video.texture = self.tex
            self._layout()
        self.tex.blit_buffer(buf, colorfmt=fmt_, bufferfmt='ubyte')
        self.shown = f                        # (assigning .texture again would reset the tex_coords of _layout)
        self.msg.text = ''
        self.canvas.ask_update()

    def _layout(self, *_):
        s, bw = self.spec, self.spec['border_w']
        x, y, W, H = self.x + bw, self.y + bw, max(1, self.width - 2 * bw), max(1, self.height - 2 * bw)
        self.back.pos, self.back.size = self.pos, self.size
        if self.frame:
            self.frame.rounded_rectangle = (self.x + bw / 2, self.y + bw / 2, self.width - bw, self.height - bw,
                                            max(0, s['radius'] - bw / 2))
        u0, u1, v0, v1 = 0.0, 1.0, 0.0, 1.0
        rx, ry, rw, rh = x, y, W, H
        if self.tex:
            fw, fh = self.tex.size
            if s['fit'] == 'cover':
                if W / H > fw / fh:
                    k = (fw * H / W) / fh
                    v0, v1 = (1 - k) / 2, (1 + k) / 2
                else:
                    k = (fh * W / H) / fw
                    u0, u1 = (1 - k) / 2, (1 + k) / 2
            elif s['fit'] == 'contain':
                sc = min(W / fw, H / fh)
                rw, rh = fw * sc, fh * sc
                rx, ry = x + (W - rw) / 2, y + (H - rh) / 2
        if s['mirror']:
            u0, u1 = u1, u0
        top, bottom = v0, v1                  # buffer row 0 = top of the picture = texture v 0
        if s['flip']:
            top, bottom = bottom, top
        self.video.pos, self.video.size = (rx, ry), (rw, rh) if self.tex else (0, 0)   # nothing before a frame
        self.video.tex_coords = (u0, bottom, u1, bottom, u1, top, u0, top)
        self.msg.pos, self.msg.size = (x, y), (W, H)
        ch = s['caption_size'] * 1.6 * (self.height / max(1, s['h'])) if s['caption'] else 0
        self.cap.pos, self.cap.size = (x, y), (W, ch)
        self.cap.font_size = s['caption_size'] * (self.height / max(1, s['h']))
        self.msg.font_size = max(10, 18 * (self.height / max(1, s['h'])))


def text_label(spec, text):
    w = Label(text=text, color=color(spec.get('color', 'text')), bold=spec.get('bold', False),
              halign=spec.get('align', 'left'), valign='middle', markup=False)
    w.bind(size=lambda o, s: setattr(o, 'text_size', s))
    return w


class Stage(FloatLayout):
    """All widgets of one screen, laid out from design pixels to the window."""
    def __init__(self, name, **kw):
        super().__init__(**kw)
        self.name, self.mtime, self.doc = name, 0, None
        self.items = []                       # (spec, kivy widget)
        self.data = {}
        self.stops = []
        self.msg = Label(text='', color=T['warn'], size_hint=(1, None), height=40, pos=(0, 0))
        with self.canvas.before:
            self.bg_color = Color(0, 0, 0, 0)
            self.bg_rect = Rectangle()
        self.bind(size=self.layout, pos=self.layout)
        self.load()
        Clock.schedule_interval(self.check_file, 1.5)
        Clock.schedule_interval(self.tick, 1)

    # file
    def path(self):
        return os.path.join(SCREENS, self.name + '.json')

    def check_file(self, dt):
        try:
            m = os.path.getmtime(self.path())
        except OSError:
            return
        if m != self.mtime:
            self.load()

    def load(self):
        try:
            self.mtime = os.path.getmtime(self.path())
            with open(self.path(), encoding='utf-8') as f:
                self.doc = json.load(f)
        except (OSError, ValueError) as e:
            self.show_msg(f'screen {self.name}: {e}')
            return
        for stop in self.stops:
            stop()
        self.stops = []
        for _, w in self.items:
            if isinstance(w, Camera):
                w.stop()                     # release the device before the screen is built again
        self.clear_widgets()
        self.items = []
        for spec in self.doc.get('widgets', []):
            w = self.make(spec)
            if w is not None:
                self.items.append((spec, w))
                self.add_widget(w)
        self.add_widget(self.msg)
        bg = self.doc.get('bg') or ''
        self.bg_color.rgba = color(bg) if bg else (0, 0, 0, 0)      # '' = the background of the display settings
        needed = {s.get('source') for s, _ in self.items if s['type'] in ('value', 'bar', 'chart')}
        interval = float(self.doc.get('interval') or 2)
        for src in sorted(n for n in needed if n in SOURCES):
            self.stops.append(smms_ui.poll(SOURCES[src], interval, lambda d, src=src: self.got(src, d),
                                           self.show_msg))
        self.layout()

    def show_msg(self, text):
        self.msg.text = text
        Clock.unschedule(self._clear_msg)
        Clock.schedule_once(self._clear_msg, 6)

    def _clear_msg(self, dt):
        self.msg.text = ''

    # widgets
    def make(self, spec):
        t = spec['type']
        if t == 'panel':
            return Panel(spec)
        if t == 'label':
            return text_label(spec, spec['text'])
        if t in ('value', 'clock'):
            return text_label(spec, '—')
        if t == 'bar':
            return Bar(spec)
        if t == 'chart':
            return LineChart(series=[{'color': color(spec['color'])}], ymax=spec['ymax'], window=spec['window'])
        if t == 'image':
            p = smms_ui.image(spec['file']) if spec.get('file') else None
            if not p:
                return text_label({'color': 'dim', 'align': 'center'}, f'image {spec.get("file") or "?"}')
            fit = spec.get('fit', 'contain')
            return Image(source=p, allow_stretch=True, keep_ratio=fit != 'stretch')
        if t == 'camera':
            return Camera(spec)
        if t == 'button':
            b = Button(text=spec['text'], color=color(spec['color']), background_normal='',
                       background_color=color(spec['bg']), halign='center', valign='middle')
            b.bind(on_release=lambda w, spec=spec: self.action(spec))
            return b
        return None

    def layout(self, *_):
        if not self.doc:
            return
        W, H = self.doc['width'], self.doc['height']
        sx, sy = self.width / W, self.height / H
        self.bg_rect.pos, self.bg_rect.size = self.pos, self.size
        for spec, w in self.items:
            w.size_hint = (None, None)
            w.size = (spec['w'] * sx, spec['h'] * sy)
            w.pos = (self.x + spec['x'] * sx, self.y + (H - spec['y'] - spec['h']) * sy)
            if 'size' in spec and hasattr(w, 'font_size') and spec['type'] != 'camera':
                w.font_size = spec['size'] * sy
        self.msg.width, self.msg.height = self.width, 40 * sy

    # data
    def got(self, src, d):
        self.data[src] = d
        now = time.time()
        for spec, w in self.items:
            if spec.get('source') != src:
                continue
            v = get_path(d, spec['path'])
            if spec['type'] == 'value':
                w.text = f'{spec["prefix"]}{fmt(v, spec["fmt"])}{spec["suffix"]}'
                n, warn, crit = number(v), number(spec['warn']), number(spec['crit'])
                w.color = (T['danger'] if n is not None and crit is not None and n >= crit else
                           T['warn'] if n is not None and warn is not None and n >= warn else color(spec['color']))
            elif spec['type'] == 'bar':
                w.set(number(v) or 0)
            elif spec['type'] == 'chart' and number(v) is not None:
                w.push(0, now, number(v), keep=4000)
                w.redraw()

    def tick(self, dt):
        for spec, w in self.items:
            if spec['type'] == 'clock':
                w.text = time.strftime(spec['format'] or '%H:%M:%S')

    def action(self, spec):
        a, target = spec['action'], spec['target']
        if a == 'screen' and target:
            self.name = target
            self.mtime = 0
            self.load()
            return
        body = json.loads(spec['body']) if spec.get('body') else {}
        call = {'post': lambda: smms_ui.api.post(target, body),
                'test_start': lambda: smms_ui.api.post('/api/tests/start', dict({'script': target}, **body)),
                'test_stop': lambda: smms_ui.api.post('/api/tests/stop')}.get(a)
        if call:
            smms_ui.in_background(call, lambda r: self.show_msg(f'{spec["text"]}: ok'),
                                  lambda m: self.show_msg(f'{spec["text"]}: {m}'))


class ScreenApp(App):
    title = 'Designer screen'

    def build(self):
        Window.clearcolor = T['bg']
        name = os.environ.get('SMMS_SCREEN') or (sys.argv[1] if len(sys.argv) > 1 else '')
        return Stage(name)

    def on_stop(self):
        for _, w in getattr(self.root, 'items', []):
            if isinstance(w, Camera):
                w.stop(wait=1.5)


if __name__ == '__main__':
    ScreenApp().run()
