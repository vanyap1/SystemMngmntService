"""Named research sessions saved as JSON files (one per session) — used by HW Utils Modbus and Terminal.

``SessionStore(folder_fn, error_cls, rows_key)``: ``folder_fn`` returns the folder (from config, so tests can move it),
errors are raised as ``error_cls(msg, status)``, ``rows_key`` names the list in ``doc['profile']`` counted in the
listing. Names are free text (letters, digits, space . , ( ) + - _), files are their slugs.
"""
import json
import os
import re
import time

MAX_BYTES = 4 * 1024 * 1024
_NAME = re.compile(r'^[\w .,()+-]{1,60}$')


class SessionStore:
    def __init__(self, folder_fn, error_cls, rows_key):
        self.folder_fn, self.Error, self.rows_key = folder_fn, error_cls, rows_key

    def slug(self, name):
        name = (name or '').strip()
        if not _NAME.match(name) or name in ('.', '..'):
            raise self.Error('Session name: letters, digits, space . , ( ) + - _ (max 60)', 400)
        return re.sub(r'[^\w.-]+', '_', name).strip('._') or 'session', name

    def _path(self, name):
        slug, name = self.slug(name)
        return os.path.join(self.folder_fn(), slug + '.json'), name

    def list(self):
        folder, out = self.folder_fn(), []
        if os.path.isdir(folder):
            for e in os.scandir(folder):
                if not e.name.endswith('.json') or e.name.startswith('.'):
                    continue
                try:
                    with open(e.path, encoding='utf-8') as f:
                        d = json.load(f)
                    p = d.get('profile') or {}
                    out.append({'name': str(d.get('name') or e.name[:-5]), 'saved': d.get('saved') or e.stat().st_mtime,
                                'rows': len(p.get(self.rows_key) or []), 'size': e.stat().st_size})
                except (OSError, ValueError, AttributeError):
                    continue
        out.sort(key=lambda s: -s['saved'])
        return out

    def save(self, name, doc, overwrite=False):
        """Write ``doc`` (+ name, saved) as the session ``name``; 409 when it exists and ``overwrite`` is false."""
        path, name = self._path(name)
        doc = dict(doc, name=name, saved=time.time())
        text = json.dumps(doc, ensure_ascii=False, indent=1)
        if len(text.encode()) > MAX_BYTES:
            raise self.Error('Session too large (clear the log / output first)', 400)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and not overwrite:
            raise self.Error(f'Session "{name}" already exists', 409)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(text)
        os.replace(tmp, path)
        return {'name': name, 'saved': doc['saved'], 'sessions': self.list()}

    def load(self, name):
        path, name = self._path(name)
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            raise self.Error(f'Session "{name}" not found', 404)
        except ValueError as e:
            raise self.Error(f'Broken session file: {e}', 500)

    def delete(self, name):
        path, name = self._path(name)
        if not os.path.isfile(path):
            raise self.Error(f'Session "{name}" not found', 404)
        os.remove(path)
        return {'sessions': self.list()}
