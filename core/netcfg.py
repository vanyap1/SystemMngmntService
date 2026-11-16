"""Settings → Network: wired / Wi-Fi configuration through NetworkManager (nmcli), every change under a checkpoint.

Safety: each change runs inside an NM checkpoint (``CheckpointCreate`` over D-Bus via busctl) with a rollback timeout.
The browser confirms it as soon as it still reaches the panel after the change (``confirm``); if the change cut the
connection, NetworkManager restores the previous state by itself when the timeout ends. ``revert`` rolls back at once.
Only one change is pending at a time.

Secrets: Wi-Fi passwords never appear on a command line or in an answer — new Wi-Fi / hotspot connections are written
as keyfiles (0600) into KEYFILE_DIR and loaded with ``nmcli connection load``; a new password of an existing keyfile
connection is written into its file the same way. Connection details never include secrets (``nmcli`` without -s).
"""
import ipaddress
import json
import os
import re
import subprocess
import threading
import time
import uuid as uuidlib

NMCLI = 'nmcli'
BUSCTL = 'busctl'
IP = 'ip'
KEYFILE_DIR = '/etc/NetworkManager/system-connections'
ROLLBACK_SECONDS = 120
# DESTROY_ALL | DELETE_NEW_CONNECTIONS | DISCONNECT_NEW_DEVICES
CHECKPOINT_FLAGS = 1 | 2 | 4
NM = ('org.freedesktop.NetworkManager', '/org/freedesktop/NetworkManager', 'org.freedesktop.NetworkManager')

TYPES = {'802-3-ethernet': 'ethernet', '802-11-wireless': 'wifi'}
IPV4_METHODS = ('auto', 'manual', 'disabled', 'shared', 'link-local')
IPV6_METHODS = ('auto', 'dhcp', 'ignore', 'disabled', 'link-local')
UUID_RE = re.compile(r'^[0-9a-fA-F-]{36}$')
IFNAME_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,15}$')

CONN_FIELDS = ('connection.id', 'connection.uuid', 'connection.type', 'connection.interface-name',
               'connection.autoconnect', 'connection.autoconnect-priority', 'ipv4.method', 'ipv4.addresses',
               'ipv4.gateway', 'ipv4.dns', 'ipv4.ignore-auto-dns', 'ipv6.method', '802-11-wireless.ssid',
               '802-11-wireless.mode', '802-11-wireless.hidden', '802-11-wireless-security.key-mgmt')


class NetError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


# ── Commands ───────────────────────────────────────────────────────────────

def _run(argv, timeout=30):
    env = dict(os.environ, LC_ALL='C', LANG='C')
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise NetError(f'{argv[0]} not found — NetworkManager is required', 501)
    except subprocess.TimeoutExpired:
        raise NetError(f'{argv[0]} timed out after {timeout} s', 504)
    if r.returncode:
        raise NetError((r.stderr or r.stdout).strip() or f'{argv[0]} failed ({r.returncode})')
    return r.stdout


def nm(*args, timeout=30):
    return _run([NMCLI, *args], timeout=timeout)


def split_terse(line):
    """Fields of one ``nmcli -t`` line (``:`` separates, ``\\:`` and ``\\\\`` are escapes)."""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == '\\' and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ':':
            out.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append(''.join(cur))
    return out


def _kv(text):
    """``field:value`` lines (nmcli -t -f a,b show) → dict; ``[n]`` suffixes collected into lists."""
    d = {}
    for line in text.splitlines():
        if ':' not in line:
            continue
        key, val = line.split(':', 1)
        m = re.match(r'^(.*)\[\d+\]$', key)
        if m:
            d.setdefault(m.group(1), []).append(val)
        else:
            d[key] = val
    return d


def _list(val):
    if isinstance(val, list):
        return [v for v in val if v]
    return [v.strip() for v in re.split(r'[,\s]+', val or '') if v.strip()]


# ── Read ───────────────────────────────────────────────────────────────────

def devices():
    out = []
    for block in nm('-t', '-f', 'GENERAL.DEVICE,GENERAL.TYPE,GENERAL.HWADDR,GENERAL.STATE,GENERAL.CONNECTION,'
                    'GENERAL.CON-UUID,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,IP6.ADDRESS', 'device', 'show').split('\n\n'):
        d = _kv(block)
        if not d.get('GENERAL.DEVICE') or d.get('GENERAL.TYPE') not in ('ethernet', 'wifi'):
            continue
        state = d.get('GENERAL.STATE', '')
        out.append({'device': d['GENERAL.DEVICE'], 'type': d['GENERAL.TYPE'], 'mac': d.get('GENERAL.HWADDR', ''),
                    'state': re.sub(r'^\d+\s*\((.*)\)$', r'\1', state), 'connected': state.startswith('100'),
                    'connection': d.get('GENERAL.CONNECTION', ''), 'uuid': d.get('GENERAL.CON-UUID', ''),
                    'ip4': _list(d.get('IP4.ADDRESS')), 'gateway': d.get('IP4.GATEWAY', ''),
                    'dns': _list(d.get('IP4.DNS')), 'ip6': _list(d.get('IP6.ADDRESS'))})
    return out


def connections():
    out = []
    for line in nm('-t', '-f', 'NAME,UUID,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY,ACTIVE,FILENAME',
                   'connection', 'show').splitlines():
        f = split_terse(line)
        if len(f) < 8 or f[2] not in TYPES:
            continue
        out.append({'name': f[0], 'uuid': f[1], 'type': TYPES[f[2]], 'device': f[3], 'autoconnect': f[4] == 'yes',
                    'priority': int(f[5]) if re.match(r'^-?\d+$', f[5]) else 0, 'active': f[6] == 'yes',
                    'file': f[7]})
    return out


def connection(uuid):
    _check_uuid(uuid)
    d = _kv(nm('-t', '-f', ','.join(CONN_FIELDS), 'connection', 'show', 'uuid', uuid))
    ctype = TYPES.get(d.get('connection.type'), d.get('connection.type', ''))
    res = {'uuid': uuid, 'name': d.get('connection.id', ''), 'type': ctype,
           'interface': d.get('connection.interface-name', ''),
           'autoconnect': d.get('connection.autoconnect') == 'yes',
           'priority': int(d.get('connection.autoconnect-priority') or 0),
           'ipv4': {'method': d.get('ipv4.method', 'auto'), 'addresses': _list(d.get('ipv4.addresses')),
                    'gateway': d.get('ipv4.gateway', '').replace('--', ''), 'dns': _list(d.get('ipv4.dns')),
                    'ignore_auto_dns': d.get('ipv4.ignore-auto-dns') == 'yes'},
           'ipv6': {'method': d.get('ipv6.method', 'auto')}}
    if ctype == 'wifi':
        res['wifi'] = {'ssid': d.get('802-11-wireless.ssid', ''), 'mode': d.get('802-11-wireless.mode', ''),
                       'hidden': d.get('802-11-wireless.hidden') == 'yes',
                       'security': d.get('802-11-wireless-security.key-mgmt', '') or 'none'}
    return res


def wifi_enabled():
    try:
        return nm('radio', 'wifi').strip() == 'enabled'
    except NetError:
        return None


def scan(ifname=None, rescan=False):
    args = ['-t', '-f', 'IN-USE,SSID,BSSID,SIGNAL,SECURITY,CHAN,FREQ,MODE', 'device', 'wifi', 'list']
    if ifname:
        _check_ifname(ifname)
        args += ['ifname', ifname]
    args += ['--rescan', 'yes' if rescan else 'no']
    known = {c['name'] for c in connections() if c['type'] == 'wifi'}
    best = {}
    for line in nm(*args, timeout=40).splitlines():
        f = split_terse(line)
        if len(f) < 8 or not f[1]:
            continue
        sig = int(f[3]) if f[3].isdigit() else 0
        net = {'ssid': f[1], 'in_use': f[0] == '*', 'signal': sig, 'security': f[4].strip() or 'open',
               'channel': f[5], 'band': '5 GHz' if f[6].startswith('5') else '2.4 GHz' if f[6].startswith('2') else f[6],
               'mode': f[7], 'known': f[1] in known}
        cur = best.get(f[1])
        if not cur or net['in_use'] or (sig > cur['signal'] and not cur['in_use']):
            if cur:
                net['in_use'] = net['in_use'] or cur['in_use']
            best[f[1]] = net
    return sorted(best.values(), key=lambda n: (not n['in_use'], -n['signal'], n['ssid'].lower()))


def client_device(addr):
    """Interface the visitor's address is reached through (``ip route get``), '' if unknown."""
    try:
        ipaddress.ip_address(addr)
    except ValueError:
        return ''
    if addr in ('127.0.0.1', '::1'):
        return 'lo'
    try:
        routes = json.loads(_run([IP, '-j', 'route', 'get', addr], timeout=5) or '[]')
        return routes[0].get('dev', '') if routes else ''
    except (NetError, ValueError, IndexError, AttributeError):
        return ''


def overview(client_addr=''):
    return {'devices': devices(), 'connections': connections(), 'wifi_enabled': wifi_enabled(),
            'client_device': client_device(client_addr), 'pending': pending(), 'hostname': os.uname().nodename,
            'rollback_seconds': ROLLBACK_SECONDS}


# ── Validation ─────────────────────────────────────────────────────────────

def _check_uuid(u):
    if not isinstance(u, str) or not UUID_RE.match(u):
        raise NetError('Invalid connection id')


def _check_ifname(n):
    if not isinstance(n, str) or not IFNAME_RE.match(n):
        raise NetError('Invalid interface name')


def check_ssid(ssid):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or any(ord(c) < 32 or c in '\\' for c in ssid):
        raise NetError('SSID: 1–32 bytes, no control characters or backslash')
    return ssid


def check_psk(psk, required=True):
    if not psk:
        if required:
            raise NetError('Password required')
        return ''
    if re.fullmatch(r'[0-9a-fA-F]{64}', psk) or (8 <= len(psk) <= 63 and all(32 <= ord(c) < 127 for c in psk)):
        return psk
    raise NetError('Wi-Fi password: 8–63 printable ASCII characters (or 64 hex digits)')


def _check_ipv4(cfg):
    method = cfg.get('method', 'auto')
    if method not in IPV4_METHODS:
        raise NetError(f'Invalid IPv4 method: {method}')
    addrs = []
    for a in _list(cfg.get('addresses', [])):
        try:
            iface = ipaddress.IPv4Interface(a if '/' in a else a + '/24')
        except ValueError:
            raise NetError(f'Invalid IPv4 address: {a} (e.g. 192.168.1.50/24)')
        addrs.append(str(iface))
    if method == 'manual' and not addrs:
        raise NetError('Static IPv4 needs at least one address')
    gw = (cfg.get('gateway') or '').strip()
    if gw:
        try:
            gw = str(ipaddress.IPv4Address(gw))
        except ValueError:
            raise NetError(f'Invalid gateway: {gw}')
    dns = []
    for a in _list(cfg.get('dns', [])):
        try:
            dns.append(str(ipaddress.ip_address(a)))
        except ValueError:
            raise NetError(f'Invalid DNS server: {a}')
    return method, addrs, gw, dns


def _modify_args(cfg):
    """nmcli ``connection modify`` arguments for the editable fields of ``cfg``."""
    args = []
    name = (cfg.get('name') or '').strip()
    if name:
        if len(name) > 64 or any(ord(c) < 32 for c in name):
            raise NetError('Invalid connection name')
        args += ['connection.id', name]
    if 'autoconnect' in cfg:
        args += ['connection.autoconnect', 'yes' if cfg['autoconnect'] else 'no']
    if 'priority' in cfg:
        try:
            prio = int(cfg['priority'])
        except (TypeError, ValueError):
            raise NetError('Priority must be a number')
        if not -999 <= prio <= 999:
            raise NetError('Priority: -999…999')
        args += ['connection.autoconnect-priority', str(prio)]
    if 'interface' in cfg:
        ifn = (cfg.get('interface') or '').strip()
        if ifn:
            _check_ifname(ifn)
        args += ['connection.interface-name', ifn]
    if isinstance(cfg.get('ipv4'), dict):
        method, addrs, gw, dns = _check_ipv4(cfg['ipv4'])
        manual = method == 'manual'
        args += ['ipv4.method', method,
                 'ipv4.addresses', ','.join(addrs) if manual else '',
                 'ipv4.gateway', gw if manual else '',
                 'ipv4.dns', ','.join(dns),
                 'ipv4.ignore-auto-dns', 'yes' if cfg['ipv4'].get('ignore_auto_dns') and dns else 'no']
    if isinstance(cfg.get('ipv6'), dict):
        m6 = cfg['ipv6'].get('method', 'auto')
        if m6 not in IPV6_METHODS:
            raise NetError(f'Invalid IPv6 method: {m6}')
        args += ['ipv6.method', m6]
    if isinstance(cfg.get('wifi'), dict) and 'hidden' in cfg['wifi']:
        args += ['802-11-wireless.hidden', 'yes' if cfg['wifi']['hidden'] else 'no']
    return args


# ── Checkpoint (pending change) ────────────────────────────────────────────

_lock = threading.Lock()
_pending = None
_last = None


def _bus(method, sig, *args, timeout=15):
    return _run([BUSCTL, 'call', NM[0], NM[1], NM[2], method, sig, *map(str, args)], timeout=timeout)


def pending():
    """The change waiting for confirmation, or the outcome of the last one."""
    global _pending, _last
    with _lock:
        if _pending and time.time() > _pending['deadline'] + 3:
            _last = dict(_pending, result='rolled back (not confirmed in time)')
            _pending = None
        if _pending:
            return dict(_pending, left=max(0, round(_pending['deadline'] - time.time())))
        return {'last': _last} if _last else None


def _guarded(label, fn):
    """Run ``fn`` under a fresh checkpoint; roll back at once if it fails."""
    global _pending, _last
    with _lock:
        if _pending and time.time() <= _pending['deadline'] + 3:
            raise NetError(f'Confirm or revert the previous change first ({_pending["label"]})', 409)
        out = _bus('CheckpointCreate', 'aouu', 0, ROLLBACK_SECONDS, CHECKPOINT_FLAGS)
        m = re.search(r'"(/org/freedesktop/NetworkManager/Checkpoint/\d+)"', out)
        if not m:
            raise NetError(f'Could not create a NetworkManager checkpoint: {out.strip()}', 500)
        path = m.group(1)
        try:
            result = fn()
        except Exception:
            try:
                _bus('CheckpointRollback', 'o', path, timeout=60)
            except NetError:
                pass
            raise
        _pending = {'path': path, 'label': label, 'created': time.time(),
                    'deadline': time.time() + ROLLBACK_SECONDS}
        _last = None
    p = pending()
    p['result'] = result
    return p


def confirm():
    global _pending, _last
    with _lock:
        if not _pending:
            raise NetError('Nothing to confirm (already confirmed or rolled back)', 409)
        _bus('CheckpointDestroy', 'o', _pending['path'])
        _last = dict(_pending, result='kept')
        _pending = None
        return {'last': _last}


def revert():
    global _pending, _last
    with _lock:
        if not _pending:
            raise NetError('Nothing to revert', 409)
        _bus('CheckpointRollback', 'o', _pending['path'], timeout=60)
        _last = dict(_pending, result='reverted')
        _pending = None
        return {'last': _last}


# ── Changes ────────────────────────────────────────────────────────────────

def _find(uuid):
    _check_uuid(uuid)
    for c in connections():
        if c['uuid'] == uuid:
            return c
    raise NetError('Connection not found', 404)


def save_connection(uuid, cfg, password=None):
    """Change a connection; an active one is re-activated so the change applies now."""
    c = _find(uuid)
    args = _modify_args(cfg)
    psk = check_psk(password, required=False) if c['type'] == 'wifi' else ''

    def run():
        if args:
            nm('connection', 'modify', 'uuid', uuid, *args)
        if psk:
            _set_keyfile_psk(c, psk)
        if c['active']:
            nm('connection', 'up', 'uuid', uuid, timeout=60)
        return {'uuid': uuid}
    return _guarded(f'Change {c["name"]}', run)


def activate(uuid):
    c = _find(uuid)
    return _guarded(f'Connect {c["name"]}', lambda: nm('connection', 'up', 'uuid', uuid, timeout=60) and None)


def deactivate(uuid):
    c = _find(uuid)
    return _guarded(f'Disconnect {c["name"]}', lambda: nm('connection', 'down', 'uuid', uuid, timeout=30) and None)


def delete(uuid):
    c = _find(uuid)
    return _guarded(f'Forget {c["name"]}', lambda: nm('connection', 'delete', 'uuid', uuid) and None)


def set_wifi(on):
    return _guarded('Wi-Fi ' + ('on' if on else 'off'), lambda: nm('radio', 'wifi', 'on' if on else 'off') and None)


def _keyfile_escape(v):
    return v.replace('\\', '\\\\').replace('\n', '').replace('\r', '')


def _write_keyfile(name, text):
    os.makedirs(KEYFILE_DIR, exist_ok=True)
    slug = re.sub(r'[^\w.-]', '_', name)[:40] or 'wifi'
    path = os.path.join(KEYFILE_DIR, f'smms-{slug}-{uuidlib.uuid4().hex[:6]}.nmconnection')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    return path


def _wifi_keyfile(uid, name, ssid, ifname, psk, security, mode='infrastructure', hidden=False, ipv4='auto'):
    lines = ['[connection]', f'id={_keyfile_escape(name)}', f'uuid={uid}', 'type=wifi', 'autoconnect=true']
    if ifname:
        lines.append(f'interface-name={ifname}')
    lines += ['', '[wifi]', f'mode={mode}', f'ssid={_keyfile_escape(ssid)}']
    if hidden:
        lines.append('hidden=true')
    if mode == 'ap':
        lines.append('band=bg')
    if psk:
        lines += ['', '[wifi-security]', f'key-mgmt={security}', f'psk={_keyfile_escape(psk)}']
        if mode == 'ap':
            lines += ['proto=rsn', 'pairwise=ccmp', 'group=ccmp']
    lines += ['', '[ipv4]', f'method={ipv4}', '', '[ipv6]', 'addr-gen-mode=default', 'method=ignore' if mode == 'ap' else 'method=auto', '']
    return '\n'.join(lines)


def _set_keyfile_psk(c, psk):
    """New password of an existing Wi-Fi connection: written into its keyfile, then reloaded."""
    path = c.get('file') or ''
    if not path.startswith(KEYFILE_DIR.rstrip('/') + '/') or not os.path.isfile(path):
        raise NetError('The password of this connection can only be changed by forgetting and re-adding it')
    with open(path, encoding='utf-8') as f:
        text = f.read()
    sec = re.search(r'(?ms)^\[wifi-security\]\n(.*?)(?=^\[|\Z)', text)
    if not sec:
        raise NetError('This network has no password (open network)')
    body = sec.group(1)
    line = f'psk={_keyfile_escape(psk)}\n'
    body = re.sub(r'(?m)^psk=.*\n?', line, body) if re.search(r'(?m)^psk=', body) else body + line
    text = text[:sec.start(1)] + body + text[sec.end(1):]
    tmp = path + '.smms-tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)
    nm('connection', 'load', path)


def _key_mgmt(security):
    s = (security or '').upper()
    if not s or s in ('OPEN', '--', 'NONE'):
        return ''
    if 'WPA3' in s and 'WPA2' not in s and 'WPA1' not in s:
        return 'sae'
    if 'WEP' in s:
        raise NetError('WEP networks are not supported')
    if '802.1X' in s:
        raise NetError('Enterprise (802.1X) networks are not supported here')
    return 'wpa-psk'


def wifi_connect(ssid, password='', ifname='', security='WPA2', hidden=False):
    """Join a Wi-Fi network: an existing connection with that SSID is updated and activated, else a new one."""
    ssid = check_ssid(ssid)
    if ifname:
        _check_ifname(ifname)
    mgmt = _key_mgmt(security)
    psk = check_psk(password, required=bool(mgmt) and not _known(ssid)) if mgmt else ''
    existing = next((c for c in connections() if c['type'] == 'wifi' and c['name'] == ssid), None)

    def run():
        if existing:
            if psk:
                _set_keyfile_psk(existing, psk)
            nm('connection', 'up', 'uuid', existing['uuid'], timeout=60)
            return {'uuid': existing['uuid']}
        uid = str(uuidlib.uuid4())
        path = _write_keyfile(ssid, _wifi_keyfile(uid, ssid, ssid, ifname, psk, mgmt or 'wpa-psk', hidden=hidden))
        try:
            nm('connection', 'load', path)
            nm('connection', 'up', 'uuid', uid, timeout=60)
        except NetError:
            try:
                nm('connection', 'delete', 'uuid', uid)
            except NetError:
                if os.path.exists(path):
                    os.remove(path)
            raise
        return {'uuid': uid}
    return _guarded(f'Join Wi-Fi {ssid}', run)


def _known(ssid):
    return any(c['type'] == 'wifi' and c['name'] == ssid for c in connections())


def hotspot(ssid, password, ifname, ipv4='shared'):
    """Access point on ``ifname`` (clients get addresses from NM's shared mode)."""
    ssid = check_ssid(ssid)
    _check_ifname(ifname)
    psk = check_psk(password, required=True)

    def run():
        uid = str(uuidlib.uuid4())
        path = _write_keyfile('hotspot-' + ssid, _wifi_keyfile(uid, f'Hotspot {ssid}', ssid, ifname, psk, 'wpa-psk',
                                                                mode='ap', ipv4=ipv4))
        nm('connection', 'load', path)
        nm('connection', 'up', 'uuid', uid, timeout=60)
        return {'uuid': uid}
    return _guarded(f'Hotspot {ssid} on {ifname}', run)
