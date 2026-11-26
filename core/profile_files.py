"""HW Utils profiles (macros, TX lists, notes) kept in git: ``hwProfiles/<kind>.json`` for kind tty (Terminal),
modbus (Modbus) and can (CAN TX lists) — shared by every host that runs this repository.

Legacy: they used to live in config.json (git-ignored, per host) under the same key. ``load`` reads that section
while the file does not exist yet; the first ``save`` writes the file and empties the section (migration).
Files written by the panel (root) are given to the owner of the repository so git can update them on pull.
"""
import json
import os

from core import config

KINDS = ('tty', 'modbus', 'can')


def _path(kind):
    if kind not in KINDS:
        raise ValueError(kind)
    return os.path.join(config.profiles_dir(), kind + '.json')


def own(path):
    """chown a file / folder the panel wrote to the owner of the repository (only when running as root)."""
    if os.geteuid() != 0:
        return
    try:
        st = os.stat(config.BASE_DIR)
        os.chown(path, st.st_uid, st.st_gid)
    except OSError:
        pass


def load(kind):
    """The saved profiles of ``kind`` ({} when none): the file in git, else the legacy config.json section."""
    path = _path(kind)
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}
    return config.get(kind) or {}


def save(kind, data):
    """Write the (already sanitised) profiles of ``kind`` atomically; move a legacy config.json section out."""
    path = _path(kind)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
        own(folder)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, path)
    own(path)
    if config.get(kind):
        config.save_key(kind, {})
    return data
