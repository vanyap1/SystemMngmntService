"""CAN trace files for HW Utils → CAN: store (tree, folders, rename, delete to .trash, upload) and the line format.

Files are candump log files (``candump -l`` / ``canplayer`` from can-utils), one frame per line::

    (1732640000.123456) can0 123#1122334455
    (1732640000.223456) can0 18FF50E5#            extended ID (8 hex digits), no data
    (1732640000.323456) can0 7FF#R2               remote frame, DLC 2
    (1732640000.423456) can0 20000020#0000000000000000   error frame (CAN_ERR_FLAG in the ID)
    (1732640000.523456) can0 123#01 T             own transmission (extra token, ignored by canplayer)

Lines starting with ``#`` are comments (the recorder writes one per recording session).
Paths from the client are relative to ``config.can_traces_dir()``: up to 3 folder levels, names of
letters, digits, space . , ( ) + - _ — files end in ``.log``.
"""
import os
import re
import shutil
import time

from core import config

EXT = '.log'
MAX_DEPTH = 3
MAX_UPLOAD = 256 * 1024 * 1024
TRASH = '.trash'
_NAME = re.compile(r'^[\w .,()+-]{1,80}$')
_LINE = re.compile(r'^\((\d+)\.(\d+)\)\s+(\S+)\s+([0-9A-Fa-f]{1,8})#(\S*)(?:\s+([RT]))?')

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF


class TraceError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def root():
    return config.can_traces_dir()


def check_path(rel, file=True):
    """Client path -> (absolute path, normalised relative path). ``file`` requires the .log extension."""
    rel = (rel or '').strip().strip('/')
    parts = rel.split('/') if rel else []
    if not parts or len(parts) > MAX_DEPTH + 1:
        raise TraceError('Invalid path')
    for p in parts:
        if not _NAME.match(p) or p in ('.', '..') or p.startswith('.'):
            raise TraceError(f'Invalid name "{p}": letters, digits, space . , ( ) + - _')
    if file and not parts[-1].lower().endswith(EXT):
        raise TraceError(f'A trace file name ends in {EXT}')
    if not file and len(parts) > MAX_DEPTH:
        raise TraceError(f'At most {MAX_DEPTH} folder levels')
    base = os.path.realpath(root())
    path = os.path.realpath(os.path.join(base, *parts))
    if os.path.dirname(path) != os.path.realpath(os.path.join(base, *parts[:-1])) or not path.startswith(base + os.sep):
        raise TraceError('Invalid path')
    return path, '/'.join(parts)


def file_name(name):
    """User input -> a file name with the .log extension (folder prefix allowed: ``dir/name``)."""
    name = (name or '').strip().strip('/')
    if name and not name.lower().endswith(EXT):
        name += EXT
    return name


def tree():
    """{name, path, dir: True, children: [...]} / {name, path, size, mtime} — folders first, newest files first."""
    base = root()
    os.makedirs(base, exist_ok=True)

    def walk(folder, rel, depth):
        dirs, files = [], []
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return []
        for e in entries:
            if e.name.startswith('.') or e.is_symlink():
                continue
            path = f'{rel}/{e.name}' if rel else e.name
            if e.is_dir() and depth < MAX_DEPTH:
                dirs.append({'name': e.name, 'path': path, 'dir': True, 'children': walk(e.path, path, depth + 1)})
            elif e.is_file() and e.name.lower().endswith(EXT):
                st = e.stat()
                files.append({'name': e.name, 'path': path, 'size': st.st_size, 'mtime': st.st_mtime})
        dirs.sort(key=lambda d: d['name'].lower())
        files.sort(key=lambda f: f['name'].lower())
        return dirs + files

    return walk(base, '', 0)


def mkdir(rel):
    path, rel = check_path(rel, file=False)
    if os.path.exists(path):
        raise TraceError(f'"{rel}" already exists', 409)
    os.makedirs(path)
    return rel


def rename(rel, new_name):
    """Rename a file or folder inside its folder (a file keeps the .log extension)."""
    path, rel = _existing(rel)
    is_dir = os.path.isdir(path)
    new_name = (new_name or '').strip()
    if not is_dir:
        new_name = file_name(new_name)
    parent = rel.rsplit('/', 1)[0] if '/' in rel else ''
    new_path, new_rel = check_path(f'{parent}/{new_name}' if parent else new_name, file=not is_dir)
    if new_path == path:
        return rel
    if os.path.exists(new_path) and os.path.realpath(new_path) != os.path.realpath(path):
        raise TraceError(f'"{new_rel}" already exists', 409)
    os.rename(path, new_path)
    return new_rel


def delete(rel):
    """Move a file or folder into ``.trash`` (time-stamped name), never remove it."""
    path, rel = _existing(rel)
    trash = os.path.join(root(), TRASH)
    os.makedirs(trash, exist_ok=True)
    target = os.path.join(trash, time.strftime('%Y%m%d-%H%M%S_') + rel.replace('/', '_'))
    shutil.move(path, target)
    return rel


def _existing(rel):
    try:
        path, rel = check_path(rel, file=True)
    except TraceError:
        path, rel = check_path(rel, file=False)
    if not os.path.exists(path):
        raise TraceError(f'"{rel}" not found', 404)
    return path, rel


def existing_file(rel):
    path, rel = check_path(rel, file=True)
    if not os.path.isfile(path):
        raise TraceError(f'"{rel}" not found', 404)
    return path, rel


def save_upload(folder, name, stream):
    """Store an uploaded candump log in ``folder`` (``''`` = root); refuses to overwrite."""
    rel = f'{folder.strip("/")}/{file_name(os.path.basename(name or ""))}' if folder else file_name(os.path.basename(name or ''))
    path, rel = check_path(rel, file=True)
    if os.path.exists(path):
        raise TraceError(f'"{rel}" already exists', 409)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.part'
    size = 0
    try:
        with open(tmp, 'wb') as f:
            while True:
                chunk = stream.read(1 << 16)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise TraceError('File too large')
                f.write(chunk)
        with open(tmp, 'rb') as f:
            head = f.read(4096).decode('utf-8', 'replace')
        if head.strip() and not any(parse_line(ln) for ln in head.splitlines()[:-1] or head.splitlines()):
            raise TraceError('Not a candump log: expected lines like "(1700000000.000000) can0 123#1122"')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return rel


# ── line format ──────────────────────────────────────────────────────────

def format_line(f, iface):
    """Frame dict (as recorded by net.CanBus) -> candump log line."""
    t = f['t']
    sec = int(t)
    usec = int(round((t - sec) * 1e6))
    if usec >= 1000000:
        sec, usec = sec + 1, usec - 1000000
    if f['dir'] == 'err':
        ident = f"{(f['can_id'] | CAN_ERR_FLAG):08X}"
    else:
        ident = f"{f['can_id']:08X}" if f['ext'] else f"{f['can_id']:03X}"
    body = f"R{f['dlc'] if f['dlc'] else ''}" if f['rtr'] else f['data'].upper()
    return f"({sec:010d}.{usec:06d}) {iface} {ident}#{body}{' T' if f['dir'] == 'tx' else ''}\n"


def parse_line(line):
    """candump log line -> {t, dir rx|tx|err, can_id, ext, rtr, dlc, data hex} or None (comment / junk)."""
    m = _LINE.match(line.strip())
    if not m:
        return None
    sec, frac, _iface, ident, body, mark = m.groups()
    t = int(sec) + int(frac) / (10 ** len(frac))
    raw = int(ident, 16)
    ext = len(ident) > 3
    if raw & CAN_ERR_FLAG and ext:
        direction, can_id = 'err', raw & CAN_EFF_MASK
        ext = False
    else:
        direction, can_id = ('tx' if mark == 'T' else 'rx'), raw & CAN_EFF_MASK
        ext = ext or bool(raw & CAN_EFF_FLAG) or can_id > 0x7FF
    rtr = body[:1].upper() == 'R'
    if rtr:
        dlc = int(body[1:]) if body[1:].isdigit() else 0
        data = ''
    else:
        if len(body) % 2 or len(body) > 16 or (body and not re.fullmatch(r'[0-9A-Fa-f]+', body)):
            return None
        data, dlc = body.lower(), len(body) // 2
    return {'t': t, 'dir': direction, 'can_id': can_id, 'ext': ext, 'rtr': rtr, 'dlc': min(dlc, 8), 'data': data}



# ── reading a file: summary (IDs, duration) + pages of frames ────────────

INDEX_EVERY = 1000          # one index entry per this many frames (random page access)
MAX_FILE_IDS = 4096
_KEY = re.compile(r'^(err|[sx]:[0-9a-f]{1,8})$')
_scans = {}                 # absolute path -> (signature, info, index)


def frame_key(fr):
    """ID key used by the file view and the replay filter: ``s:123`` / ``x:18ff50e5`` / ``err`` (direction ignored)."""
    if fr['dir'] == 'err':
        return 'err'
    return f"{'x' if fr['ext'] else 's'}:{fr['can_id']:x}"


def check_keys(keys):
    if keys is None:
        return set()
    if not isinstance(keys, list) or len(keys) > MAX_FILE_IDS or not all(isinstance(k, str) and _KEY.match(k) for k in keys):
        raise TraceError('Invalid ID list')
    return set(keys)


def _frames(f, prev=None, rel=0.0):
    """Iterate (offset, frame, rel, state before) from the current file position; ``rel`` = play time from the
    file start (gaps inside one recording session — the jump to the next session is not counted); the state
    (prev time, rel) before a frame lets reading resume at its offset."""
    pos = f.tell()
    for raw in f:
        start, pos = pos, pos + len(raw)
        if raw.startswith(b'#'):
            prev = None
            continue
        fr = parse_line(raw.decode('utf-8', 'replace'))
        if not fr:
            continue
        before = (prev, rel)
        if prev is not None and fr['t'] > prev:
            rel += fr['t'] - prev
        prev = fr['t']
        yield start, fr, rel, before


def scan(path):
    """-> (info, index) for an absolute path, cached while the file is unchanged.
    info = {frames, duration, sessions, start, end, ids: [{key, can_id, ext, count, rx, tx, err, dlc, data}], ids_full}
    index[i] = (offset, prev time, rel) before frame i × INDEX_EVERY."""
    st = os.stat(path)
    sig = (st.st_mtime_ns, st.st_size)
    cached = _scans.get(path)
    if cached and cached[0] == sig:
        return cached[1], cached[2]
    ids, index = {}, []
    n = sessions = 0
    first = last = None
    rel = 0.0
    full = False
    with open(path, 'rb') as f:
        for raw in f:
            if raw.startswith(b'# recording'):
                sessions += 1
        f.seek(0)
        for offset, fr, rel, before in _frames(f):
            if n % INDEX_EVERY == 0:
                index.append((offset,) + before)
            first = fr['t'] if first is None else first
            last = fr['t']
            n += 1
            key = frame_key(fr)
            row = ids.get(key)
            if row is None:
                if len(ids) >= MAX_FILE_IDS:
                    full = True
                    continue
                row = ids[key] = {'key': key, 'can_id': fr['can_id'], 'ext': fr['ext'], 'count': 0,
                                  'rx': 0, 'tx': 0, 'err': 0}
            row['count'] += 1
            row[fr['dir']] += 1
            row.update(dlc=fr['dlc'], data=fr['data'], rtr=fr['rtr'])
    info = {'frames': n, 'duration': rel if n else 0.0, 'sessions': max(sessions, 1) if n else 0,
            'start': first, 'end': last, 'size': st.st_size, 'ids_full': full,
            'ids': sorted(ids.values(), key=lambda r: (r['key'] == 'err', r['ext'], r['can_id']))}
    if len(_scans) > 32:
        _scans.clear()
    _scans[path] = (sig, info, index)
    return info, index


def read_frames(rel_path, start=0, limit=500, key=None):
    """A page of frames of a trace file: {frames: [... + n, rel], total, start}; ``key`` = only that ID."""
    path, _rel = existing_file(rel_path)
    info, index = scan(path)
    start, limit = max(0, int(start)), max(1, min(2000, int(limit)))
    if key is not None and not _KEY.match(key or ''):
        raise TraceError('Invalid ID key')
    out = []
    with open(path, 'rb') as f:
        if key is None:
            total = info['frames']
            if not index:
                return {'frames': [], 'total': 0, 'start': 0}
            slot = min(start // INDEX_EVERY, len(index) - 1)
            offset, prev, rel = index[slot]
            n = slot * INDEX_EVERY
            f.seek(offset)
            for _off, fr, rel, _b in _frames(f, prev, rel):
                if n >= start:
                    out.append(dict(fr, n=n, rel=rel))
                    if len(out) >= limit:
                        break
                n += 1
        else:
            row = next((r for r in info['ids'] if r['key'] == key), None)
            total = row['count'] if row else 0
            n = m = 0
            for _off, fr, rel, _b in _frames(f):
                if frame_key(fr) == key:
                    if m >= start:
                        out.append(dict(fr, n=n, rel=rel))
                        if len(out) >= limit:
                            break
                    m += 1
                n += 1
    return {'frames': out, 'total': total, 'start': start}
