"""Runtime configuration backed by config.json.

config.json layout:
    {
        "default": { ...settings used by any machine without its own section... },
        "hosts":   { "<hostname>": { ...settings of that machine... } }
    }
The effective config is BUILTIN_DEFAULTS <- "default" <- "hosts"[<this hostname>] (deep merge).
Saving from the settings page writes only the section of the current host.

Always read values through the accessor functions (or ``CFG``) at request time:
settings can be changed from the web UI, so never cache them in module-level constants.
"""
import copy
import json
import os
import secrets
import socket

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
MACROS_PATH = os.path.join(BASE_DIR, 'macros.json')
SECRET_KEY_PATH = os.path.join(BASE_DIR, '.secret_key')

HOSTNAME = socket.gethostname()

SERVICE_ACTIONS = ('start', 'stop', 'restart')

# Fallback for keys missing in config.json.
BUILTIN_DEFAULTS = {
    'app_title':       'SystemMngmntService',
    'page_title':      'SystemMngmntService',
    'device_name':     '',
    'target_dir':      os.path.expanduser('~'),
    'backup_dir':      os.path.expanduser('~'),
    'archive_name':    'backup.tar.gz',
    'upload_tmp_name': 'uploaded_update.tar.gz',
    'service_name':    'systemmngmntservice.service',
    'auth':            {'enabled': True, 'username': 'admin', 'password': 'admin'},
    'public_service_actions': ['restart'],
    'host':            '0.0.0.0',
    'port':            80,
    # Test platform; relative paths are resolved against the project directory.
    'tests_dir':       'testPlatform',
    'test_logs_dir':   'testLogs',
    # Documentation (Markdown pages, img/ and docs/ subfolders); relative to the project directory.
    'help_dir':        'help',
    # Check the panel's own git upstream for updates every N minutes while the UI is open (0 = off).
    'update_check_minutes': 60,
    # Names of I²C devices per bus, set in HW Utils → I²C: {"<bus>": {"0x41": "INA228 power monitor"}}.
    'i2c_labels': {},
    # HW Utils → Modbus: {"profiles": [{name, conn, macros, period}], "current": name} (core/modbus.check_profiles).
    'modbus': {},
    # HW Utils → Terminal: {"profiles": [{name, conn, eol, commands, view}], "current": name} (core/ttyterm.check_profiles).
    'tty': {},
    # Saved Modbus sessions (profile + results + frame log), one JSON file each; relative to the project directory.
    'modbus_sessions_dir': 'modbusSessions',
    # Saved terminal sessions (profile + macros + output + notes); relative to the project directory.
    'tty_sessions_dir': 'ttySessions',
}

# Keys that may be changed through the settings page (auth and
# public_service_actions are handled separately).
EDITABLE_KEYS = ('app_title', 'page_title', 'device_name', 'target_dir', 'backup_dir',
                 'archive_name', 'upload_tmp_name', 'service_name', 'host', 'port',
                 'tests_dir', 'test_logs_dir', 'help_dir', 'update_check_minutes')

INT_KEYS = ('port', 'update_check_minutes')

# Keys written to the host section on save.
HOST_KEYS = EDITABLE_KEYS + ('auth', 'public_service_actions', 'i2c_labels', 'modbus', 'tty')

CFG = {}        # effective config of this host
_FILE = {}      # raw config.json content


def _merge(base, override):
    """Deep-merge two dicts into a new one (override wins)."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _migrate_legacy(flat):
    """Convert the old flat config: its values become this host's config and the defaults."""
    return {
        'default': _merge(flat, {'device_name': ''}),
        'hosts':   {HOSTNAME: flat},
    }


def _write():
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(_FILE, f, indent=4, ensure_ascii=False)


def load():
    raw = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    migrated = 'default' not in raw and 'hosts' not in raw
    if migrated:
        raw = _migrate_legacy(raw) if raw else {'default': {}, 'hosts': {}}
    raw.setdefault('default', {})
    raw.setdefault('hosts', {})
    _FILE.clear()
    _FILE.update(raw)
    if migrated:
        _write()
    CFG.clear()
    CFG.update(_merge(_merge(BUILTIN_DEFAULTS, _FILE['default']), host_section() or {}))
    return CFG


def host_section():
    """This host's own section of config.json, or None if it runs on defaults."""
    return _FILE['hosts'].get(HOSTNAME)


def update(data):
    """Apply a settings payload (only whitelisted keys) and save it for this host."""
    for key in EDITABLE_KEYS:
        if key in data:
            CFG[key] = int(data[key]) if key in INT_KEYS else data[key]
    if isinstance(data.get('auth'), dict):
        auth_cfg = CFG.setdefault('auth', {})
        for k in ('enabled', 'username', 'password'):
            if k in data['auth']:
                auth_cfg[k] = data['auth'][k]
    if isinstance(data.get('public_service_actions'), list):
        CFG['public_service_actions'] = [a for a in data['public_service_actions']
                                         if a in SERVICE_ACTIONS]
    _FILE['hosts'][HOSTNAME] = {k: copy.deepcopy(CFG[k]) for k in HOST_KEYS if k in CFG}
    _write()


def save_key(key, value):
    """Set one HOST_KEYS value that is edited outside the settings form (e.g. i2c_labels) and save this host."""
    if key not in HOST_KEYS:
        raise KeyError(key)
    CFG[key] = copy.deepcopy(value)
    _FILE['hosts'][HOSTNAME] = {k: copy.deepcopy(CFG[k]) for k in HOST_KEYS if k in CFG}
    _write()


def reset_host():
    """Drop this host's section so it falls back to the defaults."""
    _FILE['hosts'].pop(HOSTNAME, None)
    _write()
    load()


def get(key, default=None):
    return CFG.get(key, default)


def target_dir():
    return CFG['target_dir']


def update_check_minutes():
    """Interval of the panel's update check in minutes; 0 = disabled."""
    try:
        return max(0, int(CFG.get('update_check_minutes', 60)))
    except (TypeError, ValueError):
        return 60


def backup_dir():
    return CFG['backup_dir']


def service_name():
    return CFG['service_name']


def _project_path(path):
    return os.path.normpath(os.path.join(BASE_DIR, os.path.expanduser(path)))


def tests_dir():
    return _project_path(CFG['tests_dir'])


def test_logs_dir():
    return _project_path(CFG['test_logs_dir'])


def modbus_sessions_dir():
    return _project_path(CFG.get('modbus_sessions_dir') or 'modbusSessions')


def tty_sessions_dir():
    return _project_path(CFG.get('tty_sessions_dir') or 'ttySessions')


def help_dir():
    return _project_path(CFG['help_dir'])


def auth():
    return CFG.get('auth', {})


def public_service_actions():
    """Service actions allowed without login."""
    return [a for a in CFG.get('public_service_actions', []) if a in SERVICE_ACTIONS]


def secret_key():
    """Persistent random session key, generated on first start (kept out of git)."""
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, 'r', encoding='utf-8') as f:
            key = f.read().strip()
        if key:
            return key
    key = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, 'w', encoding='utf-8') as f:
        f.write(key)
    os.chmod(SECRET_KEY_PATH, 0o600)
    return key


load()
