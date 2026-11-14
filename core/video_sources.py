"""Network video sources (Settings → Video): RTSP / HTTP cameras next to the local /dev/video* devices.

Kept in the local config.json of this host (``video_sources``, never in git): [{name, url, username, password,
transport}]. The URL is stored without credentials; a URL pasted with ``user:pass@`` is split. The password is
write-only for the browser (``public()`` returns ``password_set``) and is scrubbed from every message. Sources are
addressed as ``net:<name>`` by the Video popup (routes/video.py) and the camera widget of the UI designer (the
display script gets the full URLs in SMMS_VIDEO_SOURCES).
"""
import json
import re
import subprocess
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from core import config

NAME = re.compile(r'^[A-Za-z0-9][\w-]{0,29}$')
SCHEMES = ('rtsp', 'rtsps', 'http', 'https')
TRANSPORTS = ('tcp', 'udp')
MAX_SOURCES = 32
PROBE_SECONDS = 12


class SourceError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def _all():
    v = config.get('video_sources') or []
    return [s for s in v if isinstance(s, dict) and NAME.match(str(s.get('name', '')))]


def public():
    """Sources for the browser: no password."""
    return [{'name': s['name'], 'url': s.get('url', ''), 'username': s.get('username', ''),
             'password_set': bool(s.get('password')), 'transport': s.get('transport', 'tcp')} for s in _all()]


def _split(url):
    """URL -> (url without credentials, username, password)."""
    p = urlsplit((url or '').strip())
    if p.scheme.lower() not in SCHEMES or not p.hostname:
        raise SourceError('URL: rtsp://host[:port]/path (or http[s]://)')
    host = p.hostname + (f':{p.port}' if p.port else '')
    clean = urlunsplit((p.scheme.lower(), host, p.path, p.query, ''))
    return clean, unquote(p.username or ''), unquote(p.password or '')


def save(items):
    """Replace the list (from the settings tab). An empty password with ``keep_password`` keeps the stored one."""
    if not isinstance(items, list) or len(items) > MAX_SOURCES:
        raise SourceError(f'At most {MAX_SOURCES} sources')
    old = {s['name']: s for s in _all()}
    out, names = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get('name') or '').strip()
        if not NAME.match(name):
            raise SourceError(f'Name "{name}": letters, digits, _ and - (max 30)')
        if name in names:
            raise SourceError(f'Name "{name}" is used twice')
        names.add(name)
        url, u_user, u_pass = _split(it.get('url'))
        user = str(it.get('username') or u_user or '')[:80]
        pw = str(it.get('password') or u_pass or '')[:120]
        if not pw and it.get('keep_password', True) and name in old:
            pw = old[name].get('password', '')
        transport = it.get('transport') if it.get('transport') in TRANSPORTS else 'tcp'
        out.append({'name': name, 'url': url, 'username': user, 'password': pw, 'transport': transport})
    config.save_key('video_sources', out)
    return public()


def get(name):
    s = next((x for x in _all() if x['name'] == name), None)
    if not s:
        raise SourceError(f'No video source "{name}"', 404)
    return s


def full_url(src):
    """The URL with the credentials (for ffmpeg / OpenCV only — never shown)."""
    if not src.get('username'):
        return src['url']
    p = urlsplit(src['url'])
    cred = quote(src['username'], safe='') + (':' + quote(src.get('password', ''), safe='') if src.get('password') else '')
    return urlunsplit((p.scheme, f'{cred}@{p.netloc}', p.path, p.query, ''))


def urls():
    """{name: {url, transport}} with credentials, for the device display script (environment)."""
    return {s['name']: {'url': full_url(s), 'transport': s.get('transport', 'tcp')} for s in _all()}


def scrub(text, src=None):
    """Remove passwords (and user:pass@ parts) from a message."""
    text = re.sub(r'(\w+://)[^/@\s]*@', r'\1***@', str(text or ''))
    for s in ([src] if src else _all()):
        for secret in (s.get('password'), quote(s.get('password') or '', safe='')):
            if secret:
                text = text.replace(secret, '***')
    return text


def ffmpeg_input(src):
    """ffmpeg input arguments of a source."""
    args = []
    if src['url'].startswith('rtsp'):
        args += ['-rtsp_transport', src.get('transport', 'tcp')]
    return args + ['-i', full_url(src)]


def probe(name):
    """Open the stream and decode one frame: {'ok', 'video' (codec, size), 'error'}."""
    src = get(name)
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,width,height',
           '-of', 'json'] + (['-rtsp_transport', src.get('transport', 'tcp')] if src['url'].startswith('rtsp') else []) + \
          [full_url(src)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_SECONDS)
    except FileNotFoundError:
        raise SourceError('ffprobe (ffmpeg) is not installed', 500)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': f'no answer in {PROBE_SECONDS} s'}
    try:
        st = (json.loads(r.stdout or '{}').get('streams') or [{}])[0]
    except ValueError:
        st = {}
    if r.returncode == 0 and st.get('width'):
        return {'ok': True, 'video': f'{st.get("codec_name", "?")} {st["width"]}x{st["height"]}'}
    err = (r.stderr or '').strip().splitlines()
    return {'ok': False, 'error': scrub(err[-1] if err else f'ffprobe exit code {r.returncode}', src)}
