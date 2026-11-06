"""Secrets of this host (git HTTPS token) — kept OUT of every repository.

Stored in ``~/.config/systemmngmntservice/credentials.json`` of the user running the panel (root for the live
service), mode 0600. Never in config.json (that file is tracked by git) and never sent back to the browser:
``public()`` returns only whether a token is set and its last 4 characters.
"""
import json
import os

PATH = os.path.join(os.path.expanduser('~'), '.config', 'systemmngmntservice', 'credentials.json')


def _load():
    try:
        with open(PATH, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    folder = os.path.dirname(PATH)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    tmp = PATH + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PATH)


def git():
    """{'username': str, 'token': str} for HTTPS remotes (empty strings when not set)."""
    g = _load().get('git') or {}
    return {'username': str(g.get('username') or ''), 'token': str(g.get('token') or '')}


def set_git(username=None, token=None):
    """Update the git credentials; ``None`` keeps a value, ``''`` clears it."""
    data = _load()
    g = data.get('git') or {}
    if username is not None:
        g['username'] = username.strip()
    if token is not None:
        g['token'] = token.strip()
    data['git'] = g
    _save(data)


def public():
    g = git()
    t = g['token']
    return {'username': g['username'], 'token_set': bool(t), 'token_hint': ('…' + t[-4:]) if len(t) >= 8 else ('set' if t else ''),
            'path': PATH}
