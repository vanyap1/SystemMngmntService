"""Documentation store: Markdown pages in help_dir, images in help_dir/img, attachments in help_dir/docs.

Pages are addressed by their path relative to help_dir (POSIX separators, e.g. ``linux/udev.md``); they may
live in sub-folders, except the reserved top-level folders below. Markdown links to images/attachments are
relative to the page (``img/x.png`` at the top level, ``../img/x.png`` one folder down), so the files also
render in any other Markdown viewer. Deleted pages and files are moved to ``.trash/`` instead of being removed.
"""
import os
import re
import shutil
import time
from urllib.parse import quote

from core import config

IMG, ATT = 'img', 'docs'
KINDS = (IMG, ATT)
RESERVED = {IMG, ATT, 'examples', 'diagrams'}   # top-level folders that are not page folders
TRASH = '.trash'
MAX_DEPTH = 3                           # folder levels a page path may have
MAX_DOC = 2 * 1024 * 1024               # bytes of Markdown per page
MAX_UPLOAD = {IMG: 20 * 1024 * 1024, ATT: 200 * 1024 * 1024}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico'}

_SEGMENT = re.compile(r'^[\w][\w .,()&+@#-]*$')
_HEADING = re.compile(r'^#\s+(.+?)\s*#*\s*$', re.M)
_ASSET_LINK = re.compile(r'(\]\(\s*<?|\bsrc\s*=\s*["\'])((?:\.\./)*)((?:img|docs)/)')


class DocError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def root():
    return config.help_dir()


def _abs(rel):
    return os.path.join(root(), *rel.split('/'))


# ── Validation ──────────────────────────────────────────────────

def check_segment(name):
    name = (name or '').strip()
    if not name or len(name) > 120 or not _SEGMENT.match(name) or name.endswith(('.', ' ')):
        raise DocError(f'Invalid name: "{name}"')
    return name


def check_doc_path(path):
    """Normalise and validate a page path ('folder/name.md'); raises DocError."""
    path = (path or '').strip().replace('\\', '/').strip('/')
    if not path.lower().endswith('.md'):
        path += '.md'
    parts = [check_segment(p) for p in path.split('/')]
    if len(parts) - 1 > MAX_DEPTH:
        raise DocError(f'Too deep (max {MAX_DEPTH} folders)')
    if len(parts) > 1 and parts[0].lower() in RESERVED:
        raise DocError(f'"{parts[0]}" is a reserved folder')
    if parts[-1][:-3].strip() == '':
        raise DocError('Empty file name')
    return '/'.join(parts)


def _existing_doc(path):
    path = check_doc_path(path)
    full = _abs(path)
    if not os.path.isfile(full):
        raise DocError('Document not found', 404)
    return path, full


def title_of(content, path):
    m = _HEADING.search(content[:4000])
    return m.group(1).strip() if m else os.path.basename(path)[:-3].replace('_', ' ')


def safe_file_name(name, fallback='file'):
    """Upload file name: keep letters/digits/._- (Unicode too), the rest becomes '_'."""
    name = os.path.basename((name or '').replace('\\', '/')).strip()
    stem, ext = os.path.splitext(name)
    stem = re.sub(r'[^\w.-]+', '_', stem).strip('._') or fallback
    ext = re.sub(r'[^\w]', '', ext)[:10].lower()
    return stem[:100] + ('.' + ext if ext else '')


# ── Pages ───────────────────────────────────────────────────────

def list_docs():
    base = root()
    docs = []
    if not os.path.isdir(base):
        return docs
    for dirpath, dirs, files in os.walk(base):
        rel_dir = os.path.relpath(dirpath, base).replace(os.sep, '/')
        rel_dir = '' if rel_dir == '.' else rel_dir
        depth = rel_dir.count('/') + 1 if rel_dir else 0
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and depth < MAX_DEPTH
                         and not (depth == 0 and d.lower() in RESERVED))
        for name in files:
            if not name.lower().endswith('.md') or name.startswith('.'):
                continue
            rel = f'{rel_dir}/{name}' if rel_dir else name
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
                with open(full, encoding='utf-8', errors='replace') as f:
                    head = f.read(4000)
            except OSError:
                continue
            docs.append({'path': rel, 'title': title_of(head, rel), 'mtime': st.st_mtime, 'size': st.st_size})
    docs.sort(key=lambda d: (d['path'].count('/') == 0, d['path'].lower()))
    return docs


def read_doc(path):
    path, full = _existing_doc(path)
    with open(full, encoding='utf-8', errors='replace') as f:
        content = f.read()
    return {'path': path, 'content': content, 'title': title_of(content, path),
            'mtime': os.path.getmtime(full)}


def _write_text(full, content):
    os.makedirs(os.path.dirname(full), exist_ok=True)
    tmp = f'{full}.tmp{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    os.replace(tmp, full)


def save_doc(path, content, base_mtime=None, force=False):
    """Overwrite a page. ``base_mtime`` = mtime the editor loaded; a newer file on disk is a conflict (409)."""
    path, full = _existing_doc(path)
    if not isinstance(content, str):
        raise DocError('No content')
    if len(content.encode('utf-8')) > MAX_DOC:
        raise DocError('Document too large')
    if not force and base_mtime is not None:
        try:
            if abs(os.path.getmtime(full) - float(base_mtime)) > 0.001:
                raise DocError('The document was changed by someone else', 409)
        except (TypeError, ValueError):
            pass
    _write_text(full, content)
    return {'path': path, 'mtime': os.path.getmtime(full), 'title': title_of(content, path)}


def create_doc(path, title=''):
    path = check_doc_path(path)
    full = _abs(path)
    if os.path.exists(full):
        raise DocError('Already exists', 409)
    title = (title or '').strip() or os.path.basename(path)[:-3].replace('_', ' ')
    _write_text(full, f'# {title}\n\n')
    return {'path': path, 'mtime': os.path.getmtime(full), 'title': title}


def relink(content, old_depth, new_depth):
    """Fix relative img/ and docs/ links when a page moves to another folder depth."""
    if old_depth == new_depth:
        return content

    def repl(m):
        ups = len(m.group(2)) // 3
        if ups != old_depth:
            return m.group(0)            # not a link to the help root folders
        return m.group(1) + '../' * new_depth + m.group(3)
    return _ASSET_LINK.sub(repl, content)


def _prune_dirs(full):
    """Remove empty page folders left behind by a move/delete (never help_dir itself)."""
    base = os.path.realpath(root())
    d = os.path.dirname(full)
    while os.path.realpath(d) != base and os.path.realpath(d).startswith(base + os.sep):
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)


def rename_doc(path, new_path):
    path, full = _existing_doc(path)
    new_path = check_doc_path(new_path)
    new_full = _abs(new_path)
    if new_path == path:
        return {'path': path}
    if os.path.exists(new_full) and os.path.normcase(new_full) != os.path.normcase(full):
        raise DocError('Already exists', 409)
    with open(full, encoding='utf-8', errors='replace') as f:
        content = f.read()
    fixed = relink(content, path.count('/'), new_path.count('/'))
    os.makedirs(os.path.dirname(new_full), exist_ok=True)
    os.replace(full, new_full)
    if fixed != content:
        _write_text(new_full, fixed)
    _prune_dirs(full)
    return {'path': new_path, 'mtime': os.path.getmtime(new_full)}


def _to_trash(full, rel):
    dest = os.path.join(root(), TRASH, time.strftime('%Y%m%d-%H%M%S') + '__' + rel.replace('/', '__'))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(full, dest)


def delete_doc(path):
    path, full = _existing_doc(path)
    _to_trash(full, path)
    _prune_dirs(full)
    return {'path': path}


# ── Search ──────────────────────────────────────────────────────

def search(q, limit=50, per_doc=3):
    """Case-insensitive search in titles and text; every word must occur in the page."""
    words = [w for w in (q or '').lower().split() if w][:8]
    if not words:
        return []
    results = []
    for d in list_docs():
        try:
            with open(_abs(d['path']), encoding='utf-8', errors='replace') as f:
                text = f.read()
        except OSError:
            continue
        low = text.lower()
        hay = low + '\n' + d['path'].lower()
        if not all(w in hay for w in words):
            continue
        hits = []
        for n, line in enumerate(text.splitlines(), 1):
            if any(w in line.lower() for w in words):
                hits.append({'line': n, 'text': line.strip()[:200]})
                if len(hits) >= per_doc:
                    break
        title_hits = sum(w in d['title'].lower() for w in words)
        score = title_hits * 100 + sum(low.count(w) for w in words)
        results.append({**d, 'hits': hits, 'score': score})
    results.sort(key=lambda r: (-r['score'], r['path'].lower()))
    return results[:limit]


# ── Images and attachments ──────────────────────────────────────

def _kind_dir(kind):
    if kind not in KINDS:
        raise DocError('Unknown kind')
    return os.path.join(root(), kind)


def list_assets(kind):
    folder = _kind_dir(kind)
    if not os.path.isdir(folder):
        return []
    texts = []
    for d in list_docs():
        try:
            with open(_abs(d['path']), encoding='utf-8', errors='replace') as f:
                texts.append((d['path'], f.read()))
        except OSError:
            pass
    items = []
    for e in sorted(os.scandir(folder), key=lambda e: e.name.lower()):
        if not e.is_file() or e.name.startswith('.'):
            continue
        needle = f'{kind}/{e.name}'
        quoted = f'{kind}/{quote(e.name)}'
        used = [p for p, t in texts if needle in t or quoted in t]
        st = e.stat()
        items.append({'name': e.name, 'size': st.st_size, 'mtime': st.st_mtime, 'used_by': used,
                      'image': os.path.splitext(e.name)[1].lower() in IMG_EXT})
    return items


def save_upload(kind, storage):
    """Store an uploaded file (werkzeug FileStorage) under a unique safe name; returns the name."""
    folder = _kind_dir(kind)
    name = safe_file_name(storage.filename, 'image' if kind == IMG else 'file')
    stem, ext = os.path.splitext(name)
    if kind == IMG and ext.lower() not in IMG_EXT:
        raise DocError(f'Not an image: {name}')
    os.makedirs(folder, exist_ok=True)
    data = storage.read(MAX_UPLOAD[kind] + 1)
    if len(data) > MAX_UPLOAD[kind]:
        raise DocError(f'File too large (max {MAX_UPLOAD[kind] // 1048576} MB)', 413)
    n = 1
    while os.path.exists(os.path.join(folder, name)):
        with open(os.path.join(folder, name), 'rb') as f:
            if f.read() == data:
                return name                      # same file uploaded again
        n += 1
        name = f'{stem}-{n}{ext}'
    with open(os.path.join(folder, name), 'wb') as f:
        f.write(data)
    return name


def delete_asset(kind, name):
    folder = _kind_dir(kind)
    if not name or name != os.path.basename(name) or name.startswith('.'):
        raise DocError('Invalid name')
    full = os.path.join(folder, name)
    if not os.path.isfile(full):
        raise DocError('File not found', 404)
    _to_trash(full, f'{kind}/{name}')
    return {'name': name}


def file_path(rel):
    """Absolute path of any non-hidden file inside help_dir (for serving), or None."""
    parts = (rel or '').replace('\\', '/').split('/')
    if not rel or any(not p or p.startswith('.') for p in parts):
        return None
    full = os.path.realpath(_abs('/'.join(parts)))
    base = os.path.realpath(root())
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return None
    return full
