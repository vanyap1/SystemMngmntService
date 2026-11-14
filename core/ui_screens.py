"""Screens of the visual UI designer (page UI): UI/screens/<name>.json, shown on the device by UI/screen_runner.py.

A screen = {title, width, height, bg, interval, widgets: [{id, type, x, y, w, h, ...props}]} in design pixels with the
origin at the top left (the runner scales it to the real screen). Widgets show static text / pictures, values of the
panel's API (``source`` + dotted ``path``, e.g. monitor ``current.cpu.pct``), bars, charts, a clock, and buttons with
actions (another screen, an API POST, start / stop a test). Everything is checked here (types, numbers, colours,
lengths) before it is written; deleting moves the file to UI/screens/.trash.
"""
import json
import os
import re
import shutil
import time

from core import config

NAME = re.compile(r'^[A-Za-z0-9][\w-]{0,39}$')
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
THEME_KEYS = ('bg', 'panel', 'panel2', 'border', 'text', 'dim', 'accent', 'info', 'warn', 'danger', 'ok')
# the same colours as UI/smms_ui.THEME (what the device draws) — the editor previews with them (tested equal)
THEME_HEX = {'bg': '#111111', 'panel': '#1a1a1a', 'panel2': '#232323', 'border': '#2a2a2a', 'text': '#dddddd',
             'dim': '#777777', 'accent': '#4ec9b0', 'info': '#7ec8f5', 'warn': '#e8a838', 'danger': '#f44747',
             'ok': '#4ec9b0'}
IMAGE = re.compile(r'^[\w.() -]{1,100}\.(png|jpe?g)$', re.I)
PATH = re.compile(r'^[\w.-]{0,120}$')
DEVICE = re.compile(r'^(/dev/video\d{1,3}|net:[A-Za-z0-9][\w-]{0,29})$')    # V4L2 or a network source
SIZE = re.compile(r'^\d{2,5}x\d{2,5}$')
MAX_WIDGETS = 300
SOURCES = {    # API sources a widget can show; paths offered in the editor (any dotted path works)
    'monitor': {'url': '/api/monitor', 'paths': [
        'current.cpu.pct', 'current.cpu.freq_mhz', 'current.cpu.count', 'current.mem.pct', 'current.mem.used',
        'current.mem.total', 'current.temp', 'current.net.iface', 'current.net.rx_rate', 'current.net.tx_rate',
        'current.net.addrs.0', 'current.procs', 'uptime', 'hostname', 'job.title', 'job.progress.percent']},
    'tests': {'url': '/api/tests/status', 'paths': [
        'run.state', 'run.script', 'run.serial', 'run.elapsed', 'run.counts.PASS', 'run.counts.FAIL',
        'run.counts.ERROR', 'run.prompt.message']},
}
FMTS = ('raw', 'int', '1dp', '2dp', 'percent', 'bytes', 'rate', 'uptime')
ACTIONS = ('none', 'screen', 'post', 'test_start', 'test_stop')
ALIGNS = ('left', 'center', 'right')
FITS = ('contain', 'cover', 'stretch')
# props per widget type: name -> (kind, default); kinds: str/N, int lo..hi, float lo..hi, enum, color, bool
TYPES = {
    'panel':  {'color': ('color', 'panel'), 'radius': ('int', 8, 0, 200)},
    'label':  {'text': ('str', 'Text', 300), 'size': ('int', 32, 6, 400), 'color': ('color', 'text'),
               'align': ('enum', 'left', ALIGNS), 'bold': ('bool', False)},
    'value':  {'source': ('enum', 'monitor', tuple(SOURCES)), 'path': ('path', 'current.cpu.pct'),
               'fmt': ('enum', 'int', FMTS), 'prefix': ('str', '', 40), 'suffix': ('str', ' %', 40),
               'size': ('int', 48, 6, 400), 'color': ('color', 'text'), 'align': ('enum', 'left', ALIGNS),
               'bold': ('bool', True), 'warn': ('str', '', 20), 'crit': ('str', '', 20)},
    'bar':    {'source': ('enum', 'monitor', tuple(SOURCES)), 'path': ('path', 'current.mem.pct'),
               'max': ('float', 100, 0.001, 1e12), 'color': ('color', 'accent')},
    'chart':  {'source': ('enum', 'monitor', tuple(SOURCES)), 'path': ('path', 'current.cpu.pct'),
               'window': ('int', 300, 10, 3600), 'ymax': ('float', 100, 0, 1e12), 'color': ('color', 'info')},
    'image':  {'file': ('image', ''), 'fit': ('enum', 'contain', FITS)},
    'button': {'text': ('str', 'Button', 80), 'size': ('int', 32, 6, 400), 'color': ('color', 'text'),
               'bg': ('color', 'panel2'), 'action': ('enum', 'none', ACTIONS), 'target': ('str', '', 200),
               'body': ('str', '', 2000)},
    'camera': {'device': ('device', '/dev/video0'), 'resolution': ('size', '640x480'), 'fps': ('int', 15, 1, 60),
               'fit': ('enum', 'cover', FITS), 'border': ('color', 'accent'), 'border_w': ('int', 4, 0, 60),
               'radius': ('int', 8, 0, 200), 'mirror': ('bool', False), 'flip': ('bool', False),
               'caption': ('str', '', 80), 'caption_size': ('int', 24, 6, 200)},
    'clock':  {'format': ('str', '%H:%M:%S', 40), 'size': ('int', 48, 6, 400), 'color': ('color', 'text'),
               'align': ('enum', 'right', ALIGNS)},
}


class ScreenError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def screens_dir():
    return os.path.join(config.BASE_DIR, 'UI', 'screens')


def images_dir():
    return os.path.join(config.BASE_DIR, 'UI', 'images')


def _path(name):
    if not NAME.match(name or ''):
        raise ScreenError('Screen name: letters, digits, _ and - (max 40)')
    return os.path.join(screens_dir(), name + '.json')


def _num(v, default, lo, hi, kind=float):
    try:
        v = kind(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _prop(kind, v):
    k = kind[0]
    if k == 'str':
        return str(v if v is not None else kind[1])[:kind[2]]
    if k == 'int':
        return int(_num(v, kind[1], kind[2], kind[3], int))
    if k == 'float':
        return _num(v, kind[1], kind[2], kind[3])
    if k == 'enum':
        return v if v in kind[2] else kind[1]
    if k == 'bool':
        return bool(v)
    if k == 'color':
        return v if isinstance(v, str) and (v in THEME_KEYS or COLOR.match(v)) else kind[1]
    if k == 'path':
        return v if isinstance(v, str) and PATH.match(v) else kind[1]
    if k == 'image':
        return v if isinstance(v, str) and IMAGE.match(v) else ''
    if k == 'device':
        return v if isinstance(v, str) and DEVICE.match(v) else kind[1]
    if k == 'size':
        return v if isinstance(v, str) and SIZE.match(v) else kind[1]
    raise ValueError(k)


def check(doc):
    """Client screen -> clean screen (unknown widget types / props dropped, values clamped)."""
    doc = doc if isinstance(doc, dict) else {}
    w = int(_num(doc.get('width'), 1920, 160, 7680, int))
    h = int(_num(doc.get('height'), 1080, 120, 4320, int))
    bg = doc.get('bg') if isinstance(doc.get('bg'), str) and (doc.get('bg') in THEME_KEYS or COLOR.match(doc.get('bg'))) else ''
    out = {'title': str(doc.get('title') or '')[:80], 'width': w, 'height': h, 'bg': bg,
           'interval': _num(doc.get('interval'), 2, 0.5, 60), 'widgets': []}
    widgets = doc.get('widgets') if isinstance(doc.get('widgets'), list) else []
    if len(widgets) > MAX_WIDGETS:
        raise ScreenError(f'At most {MAX_WIDGETS} widgets')
    seen = set()
    for i, src in enumerate(widgets):
        if not isinstance(src, dict) or src.get('type') not in TYPES:
            continue
        wid = str(src.get('id') or '')[:20]
        if not re.match(r'^[\w-]{1,20}$', wid) or wid in seen:
            wid = f'w{i + 1}'
            while wid in seen:
                wid += 'x'
        seen.add(wid)
        x = int(_num(src.get('x'), 0, -w, 2 * w, int))
        y = int(_num(src.get('y'), 0, -h, 2 * h, int))
        ww = int(_num(src.get('w'), 200, 4, 4 * w, int))
        hh = int(_num(src.get('h'), 80, 4, 4 * h, int))
        item = {'id': wid, 'type': src['type'], 'x': x, 'y': y, 'w': ww, 'h': hh}
        for key, kind in TYPES[src['type']].items():
            item[key] = _prop(kind, src.get(key, kind[1]))
        if item['type'] == 'button' and item['action'] == 'screen' and item['target'] and not NAME.match(item['target']):
            raise ScreenError(f'Button {wid}: unknown screen name "{item["target"]}"')
        if item['type'] == 'button' and item['action'] == 'post' and not item['target'].startswith('/api/'):
            raise ScreenError(f'Button {wid}: the POST target must be an /api/... path')
        if item['type'] == 'button' and item['body']:
            try:
                json.loads(item['body'])
            except ValueError:
                raise ScreenError(f'Button {wid}: the body is not JSON')
        out['widgets'].append(item)
    return out


def list_screens():
    try:
        names = sorted(n[:-5] for n in os.listdir(screens_dir()) if n.endswith('.json') and NAME.match(n[:-5]))
    except OSError:
        return []
    out = []
    for n in names:
        try:
            d = load(n)
            out.append({'name': n, 'title': d['title'], 'widgets': len(d['widgets']),
                        'mtime': os.path.getmtime(_path(n))})
        except (ScreenError, OSError, ValueError):
            continue
    return out


def load(name):
    p = _path(name)
    try:
        with open(p, encoding='utf-8') as f:
            return check(json.load(f))
    except FileNotFoundError:
        raise ScreenError(f'No screen {name}', 404)
    except ValueError:
        raise ScreenError(f'Screen {name} is not valid JSON', 500)


def save(name, doc):
    p = _path(name)
    clean = check(doc)
    os.makedirs(screens_dir(), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(clean, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)           # atomic: the runner on the device reloads a complete file
    _own(p)
    return clean


def _own(path):
    """Files written by the panel (root) belong to the project owner, like the rest of UI/."""
    if os.geteuid() == 0:
        try:
            st = os.stat(config.BASE_DIR)
            os.chown(path, st.st_uid, st.st_gid)
        except OSError:
            pass


def delete(name):
    p = _path(name)
    if not os.path.isfile(p):
        raise ScreenError(f'No screen {name}', 404)
    trash = os.path.join(screens_dir(), '.trash')
    os.makedirs(trash, exist_ok=True)
    shutil.move(p, os.path.join(trash, f'{name}_{time.strftime("%Y%m%d_%H%M%S")}.json'))


def images():
    try:
        return sorted(n for n in os.listdir(images_dir()) if IMAGE.match(n))
    except OSError:
        return []


def image_path(name):
    if not IMAGE.match(name or '') or '/' in name:
        return None
    p = os.path.join(images_dir(), name)
    return p if os.path.isfile(p) else None


def meta():
    """What the editor needs: widget types with their props, sources and paths, formats, theme colour names."""
    # props as [[key, [kind, default, ...]], ...] — a list keeps the order (jsonify sorts dict keys)
    return {'types': {t: [[k, list(v) if not isinstance(v[-1], tuple) else [v[0], v[1], list(v[2])]]
                          for k, v in props.items()] for t, props in TYPES.items()},
            'sources': SOURCES, 'fmts': FMTS, 'actions': ACTIONS, 'theme': THEME_KEYS, 'theme_hex': THEME_HEX}
