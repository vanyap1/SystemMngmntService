"""Settings → Network → Access point & DHCP: Wi-Fi client / access point switch, DHCP pool, MAC → IP reservations,
connected clients and the data of the network map. Built on core/netcfg.py (nmcli, checkpoints).

The access point is one NetworkManager keyfile (KEYFILE_DIR/AP_FILE, 0600) written by this module: Wi-Fi in ``ap``
mode with ``ipv4.method=shared`` — NetworkManager then runs its own dnsmasq for the interface (DHCP + DNS + NAT to the
uplink). The pool and lease time are the keyfile's ``shared-dhcp-range`` / ``shared-dhcp-lease-time`` (NM ≥ 1.42).
NetworkManager stays the only store of the AP settings (and of its password — never in config.json, never returned).

Reservations (MAC → IP) are lines of HOSTS_FILE, given to NM's dnsmasq by ``dhcp-hostsfile`` in
DNSMASQ_DIR/CONF_NAME (NM starts its shared dnsmasq with ``--conf-dir=`` that folder). dnsmasq re-reads the hosts
file on SIGHUP, so editing reservations never interrupts the access point. The hosts file lives outside the conf
folder on purpose: dnsmasq would parse every file there as a config.

Every change of the link (mode switch, AP settings, pool / address) goes through ``netcfg._guarded`` — a checkpoint
that NetworkManager rolls back unless the browser confirms. Reservations are DHCP data only (no link change).
"""
import configparser
import ipaddress
import json
import os
import re
import shutil
import signal
import time
import uuid as uuidlib

from core import netcfg
from core.netcfg import NetError

AP_FILE = 'smms-ap.nmconnection'
AP_NAME = 'SMMS Access Point'
AP_PRIORITY = 100
DNSMASQ_DIR = '/etc/NetworkManager/dnsmasq-shared.d'
CONF_NAME = 'smms-dhcp.conf'
HOSTS_FILE = '/etc/NetworkManager/smms-dhcp.hosts'
LEASES = '/var/lib/NetworkManager/dnsmasq-{ifname}.leases'
PIDFILE = '/run/nm-dnsmasq-{ifname}.pid'
IW = 'iw'
MIN_NM = (1, 42)

DEFAULTS = {'ssid': '', 'ifname': '', 'security': 'wpa-psk', 'band': 'bg', 'channel': 0, 'hidden': False,
            'address': '10.10.10.1', 'prefix': 24, 'start': '10.10.10.2', 'end': '10.10.10.254', 'lease': 3600}
BANDS = {'bg': '2.4 GHz', 'a': '5 GHz'}
CHANNELS = {'bg': list(range(1, 14)), 'a': [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128,
                                           132, 136, 140, 144, 149, 153, 157, 161, 165]}
LEASE_RANGE = (120, 7 * 86400)
MAC_RE = re.compile(r'^([0-9a-f]{2}:){5}[0-9a-f]{2}$')
HOST_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')
MAX_RESERVATIONS = 512


# ── Files ──────────────────────────────────────────────────────────────────

def ap_path():
    return os.path.join(netcfg.KEYFILE_DIR, AP_FILE)


def _write_private(path, text, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.smms-tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def _read_keyfile():
    """The AP keyfile as a ConfigParser, or None."""
    path = ap_path()
    if not os.path.isfile(path):
        return None
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read(path, encoding='utf-8')
    except configparser.Error as exc:
        raise NetError(f'Cannot read {path}: {exc}', 500)
    return cp


def ap_settings():
    """Current AP settings (defaults where nothing is saved). No password — only whether one is set."""
    s = dict(DEFAULTS, ssid=os.uname().nodename[:32], configured=False, uuid='', has_password=False, autostart=False)
    cp = _read_keyfile()
    if cp is None:
        return s
    g = lambda sec, key, d='': cp.get(sec, key, fallback=d)
    s.update(configured=True, uuid=g('connection', 'uuid'), ifname=g('connection', 'interface-name'),
             autostart=g('connection', 'autoconnect', 'true') == 'true', ssid=g('wifi', 'ssid'),
             band=g('wifi', 'band', 'bg') or 'bg', hidden=g('wifi', 'hidden') == 'true',
             has_password=bool(g('wifi-security', 'psk')),
             security='wpa-psk' if cp.has_section('wifi-security') else 'none')
    try:
        s['channel'] = int(g('wifi', 'channel', '0') or 0)
    except ValueError:
        s['channel'] = 0
    addr = g('ipv4', 'address1').split(',')[0]
    if addr:
        try:
            iface = ipaddress.IPv4Interface(addr)
            s['address'], s['prefix'] = str(iface.ip), iface.network.prefixlen
        except ValueError:
            pass
    rng = g('ipv4', 'shared-dhcp-range').split(',')
    if len(rng) == 2:
        s['start'], s['end'] = rng[0].strip(), rng[1].strip()
    lease = g('ipv4', 'shared-dhcp-lease-time')
    if lease.isdigit():
        s['lease'] = int(lease)
    return s


def _psk_from_file():
    cp = _read_keyfile()
    return cp.get('wifi-security', 'psk', fallback='') if cp else ''


def _esc(v):
    return netcfg._keyfile_escape(str(v))


def _keyfile_text(s, psk, autostart):
    lines = ['[connection]', f'id={AP_NAME}', f'uuid={s["uuid"]}', 'type=wifi',
             f'interface-name={s["ifname"]}', f'autoconnect={"true" if autostart else "false"}',
             f'autoconnect-priority={AP_PRIORITY}', '',
             '[wifi]', 'mode=ap', f'ssid={_esc(s["ssid"])}', f'band={s["band"]}']
    if s['channel']:
        lines.append(f'channel={s["channel"]}')
    if s['hidden']:
        lines.append('hidden=true')
    if s['security'] != 'none':
        lines += ['', '[wifi-security]', 'key-mgmt=wpa-psk', f'psk={_esc(psk)}', 'proto=rsn', 'pairwise=ccmp',
                  'group=ccmp']
    lines += ['', '[ipv4]', 'method=shared', f'address1={s["address"]}/{s["prefix"]}',
              f'shared-dhcp-range={s["start"]},{s["end"]}', f'shared-dhcp-lease-time={s["lease"]}',
              '', '[ipv6]', 'addr-gen-mode=default', 'method=ignore', '']
    return '\n'.join(lines)


def ensure_dnsmasq_conf():
    """``dhcp-hostsfile`` for NM's shared dnsmasq. True when the file was created now (dnsmasq needs a restart)."""
    path = os.path.join(DNSMASQ_DIR, CONF_NAME)
    text = ('# Written by SystemMngmntService (Settings → Network → Access point & DHCP).\n'
            f'dhcp-hostsfile={HOSTS_FILE}\n')
    if not os.path.exists(HOSTS_FILE):
        _write_private(HOSTS_FILE, '', 0o644)
    try:
        with open(path, encoding='utf-8') as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    _write_private(path, text, 0o644)
    return True


# ── Validation ─────────────────────────────────────────────────────────────

def _ip(v, what):
    try:
        return ipaddress.IPv4Address(str(v).strip())
    except ValueError:
        raise NetError(f'{what}: invalid IPv4 address "{v}"')


def check_settings(s):
    """Validates a full settings dict in place (normalised values)."""
    s['ssid'] = netcfg.check_ssid(s.get('ssid'))
    if s.get('ifname'):
        netcfg._check_ifname(s['ifname'])
    else:
        raise NetError('Choose the Wi-Fi adapter for the access point')
    if s.get('security') not in ('wpa-psk', 'none'):
        raise NetError('Security: WPA2 or open')
    if s.get('band') not in BANDS:
        raise NetError('Band: 2.4 or 5 GHz')
    try:
        s['channel'] = int(s.get('channel') or 0)
        s['prefix'] = int(s.get('prefix'))
        s['lease'] = int(s.get('lease'))
    except (TypeError, ValueError):
        raise NetError('Channel, prefix and lease time must be numbers')
    if s['channel'] and s['channel'] not in CHANNELS[s['band']]:
        raise NetError(f'Channel {s["channel"]} is not a {BANDS[s["band"]]} channel')
    s['hidden'] = bool(s.get('hidden'))
    if not 8 <= s['prefix'] <= 30:
        raise NetError('Prefix: /8 … /30')
    addr = _ip(s.get('address'), 'Access point address')
    net = ipaddress.IPv4Network(f'{addr}/{s["prefix"]}', strict=False)
    if addr in (net.network_address, net.broadcast_address):
        raise NetError(f'{addr} is the network / broadcast address of {net}')
    if not addr.is_private:
        raise NetError(f'{addr} is not a private address (use 10.x, 172.16–31.x or 192.168.x)')
    start, end = _ip(s.get('start'), 'Pool start'), _ip(s.get('end'), 'Pool end')
    for a, what in ((start, 'Pool start'), (end, 'Pool end')):
        if a not in net or a in (net.network_address, net.broadcast_address):
            raise NetError(f'{what} {a} is outside {net} (or its network / broadcast address)')
    if start > end:
        raise NetError('Pool start must not be after its end')
    if start <= addr <= end:
        raise NetError(f'The pool {start} – {end} contains the access point address {addr}')
    if not LEASE_RANGE[0] <= s['lease'] <= LEASE_RANGE[1]:
        raise NetError(f'Lease time: {LEASE_RANGE[0]} s … {LEASE_RANGE[1] // 86400} days')
    s.update(address=str(addr), start=str(start), end=str(end))
    return s


def check_reservations(items, settings=None):
    if not isinstance(items, list) or len(items) > MAX_RESERVATIONS:
        raise NetError(f'Reservations: a list of at most {MAX_RESERVATIONS}')
    s = settings or ap_settings()
    net = ipaddress.IPv4Network(f'{s["address"]}/{s["prefix"]}', strict=False)
    out, macs, ips = [], set(), set()
    for r in items:
        if not isinstance(r, dict):
            raise NetError('Invalid reservation')
        mac = str(r.get('mac', '')).strip().lower().replace('-', ':')
        if not MAC_RE.match(mac):
            raise NetError(f'Invalid MAC address "{r.get("mac", "")}" (aa:bb:cc:dd:ee:ff)')
        ip = _ip(r.get('ip', ''), f'Reservation {mac}')
        if ip not in net or ip in (net.network_address, net.broadcast_address):
            raise NetError(f'{ip} is outside the access point network {net}')
        if str(ip) == s['address']:
            raise NetError(f'{ip} is the address of the access point itself')
        name = str(r.get('name') or '').strip()
        if name and not HOST_RE.match(name):
            raise NetError(f'Name "{name}": letters, digits and "-", up to 63 characters')
        if mac in macs:
            raise NetError(f'MAC {mac} is reserved twice')
        if ip in ips:
            raise NetError(f'IP {ip} is reserved twice')
        macs.add(mac)
        ips.add(ip)
        out.append({'mac': mac, 'ip': str(ip), 'name': name})
    return sorted(out, key=lambda x: ipaddress.IPv4Address(x['ip']))


def _which(cmd):
    """Full path of a tool, also in the sbin folders a normal user's PATH lacks (iw, dnsmasq)."""
    return shutil.which(cmd, path=os.environ.get('PATH', '') + ':/usr/sbin:/sbin:/usr/local/sbin')


def _has(cmd):
    return bool(_which(cmd))


def nm_version():
    try:
        m = re.search(r'(\d+)\.(\d+)', netcfg.nm('--version'))
        return (int(m.group(1)), int(m.group(2))) if m else None
    except NetError:
        return None


# ── Reservations and clients ───────────────────────────────────────────────

def reservations():
    out = []
    try:
        with open(HOSTS_FILE, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(',')]
        mac = next((p.lower() for p in parts if MAC_RE.match(p.lower())), '')
        ip = next((p for p in parts if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', p)), '')
        name = next((p for p in parts if p and p.lower() != mac and p != ip and HOST_RE.match(p)), '')
        if mac and ip:
            out.append({'mac': mac, 'ip': ip, 'name': name})
    return out


def _dnsmasq_pid(ifname):
    try:
        with open(PIDFILE.format(ifname=ifname)) as f:
            pid = int(f.read().strip())
        with open(f'/proc/{pid}/comm') as f:
            return pid if f.read().strip() == 'dnsmasq' else None
    except (OSError, ValueError):
        return None


def set_reservations(items):
    """Write HOSTS_FILE and make the running dnsmasq re-read it (no interruption of the access point)."""
    s = ap_settings()
    res = check_reservations(items, s)
    text = '# MAC,IP[,name] — written by SystemMngmntService; dnsmasq re-reads it on SIGHUP\n' + \
        ''.join(f'{r["mac"]},{r["ip"]}{"," + r["name"] if r["name"] else ""}\n' for r in res)
    created = ensure_dnsmasq_conf()
    _write_private(HOSTS_FILE, text, 0o644)
    reloaded = restart = False
    pid = _dnsmasq_pid(s['ifname']) if s['ifname'] else None
    if pid and not created:
        try:
            os.kill(pid, signal.SIGHUP)
            reloaded = True
        except OSError:
            pass
    elif pid:
        restart = True      # dnsmasq was started before the conf existed: it does not know the hosts file yet
    return {'reservations': res, 'reloaded': reloaded, 'restart_needed': restart}


def _leases(ifname):
    out = []
    try:
        with open(LEASES.format(ifname=ifname), encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        f = line.split()
        if len(f) >= 4 and f[0].isdigit():
            out.append({'expires': int(f[0]), 'mac': f[1].lower(), 'ip': f[2], 'hostname': '' if f[3] == '*' else f[3]})
    return out


def _stations(ifname):
    """Associated stations from ``iw dev <if> station dump`` (None when iw is missing / fails)."""
    if not _has(IW):
        return None
    try:
        text = netcfg._run([_which(IW) or IW, 'dev', ifname, 'station', 'dump'], timeout=5)
    except NetError:
        return None
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r'^Station\s+([0-9a-fA-F:]{17})', line)
        if m:
            cur = out.setdefault(m.group(1).lower(), {})
            continue
        if cur is None or ':' not in line:
            continue
        k, v = (x.strip() for x in line.split(':', 1))
        if k == 'signal':
            n = re.match(r'-?\d+', v)
            cur['signal'] = int(n.group()) if n else None
        elif k == 'connected time':
            cur['connected'] = int(re.sub(r'\D', '', v) or 0)
        elif k == 'inactive time':
            cur['inactive_ms'] = int(re.sub(r'\D', '', v) or 0)
        elif k in ('rx bytes', 'tx bytes'):
            cur[k.replace(' ', '_')] = int(re.sub(r'\D', '', v) or 0)
        elif k == 'tx bitrate':
            cur['bitrate'] = v.split(' MBit/s')[0] + ' Mbit/s' if 'MBit/s' in v else v
    return out


def _neigh(ifname):
    try:
        rows = json.loads(netcfg._run([netcfg.IP, '-j', 'neigh', 'show', 'dev', ifname], timeout=5) or '[]')
    except (NetError, ValueError):
        return {}
    out = {}
    for r in rows:
        mac = (r.get('lladdr') or '').lower()
        if mac and ':' not in (r.get('dst') or ''):
            st = r.get('state') or []
            out[mac] = {'ip': r.get('dst', ''), 'state': (st[0] if isinstance(st, list) and st else str(st)).lower()}
    return out


def clients(ifname=None):
    """Devices on the access point: DHCP leases + associated stations + neighbours, joined by MAC."""
    s = ap_settings()
    ifname = ifname or s['ifname']
    if not ifname:
        return {'clients': [], 'stations': False}
    res = {r['mac']: r for r in reservations()}
    leases = {l['mac']: l for l in _leases(ifname)}
    stations = _stations(ifname)
    neigh = _neigh(ifname)
    now = time.time()
    macs = list(dict.fromkeys([*(stations or {}), *leases, *(m for m, n in neigh.items() if n['state'] in ('reachable', 'stale', 'delay', 'probe'))]))
    out = []
    for mac in macs:
        l, st, n, r = leases.get(mac, {}), (stations or {}).get(mac), neigh.get(mac, {}), res.get(mac)
        out.append({'mac': mac, 'ip': l.get('ip') or n.get('ip', ''), 'hostname': l.get('hostname', ''),
                    'expires_in': max(0, l['expires'] - int(now)) if l.get('expires') else None,
                    'online': bool(st) if stations is not None else n.get('state') in ('reachable', 'delay', 'probe'),
                    'signal': st.get('signal') if st else None, 'connected': st.get('connected') if st else None,
                    'bitrate': st.get('bitrate', '') if st else '', 'rx_bytes': st.get('rx_bytes') if st else None,
                    'tx_bytes': st.get('tx_bytes') if st else None, 'neigh': n.get('state', ''),
                    'reserved': r['ip'] if r else '', 'name': r['name'] if r else ''})
    out.sort(key=lambda c: (not c['online'], ipaddress.IPv4Address(c['ip']) if c['ip'] else ipaddress.IPv4Address('255.255.255.255')))
    return {'clients': out, 'stations': stations is not None}


# ── Status ─────────────────────────────────────────────────────────────────

def _ap_capable(ifname):
    """True / False from ``iw phy <phy> info`` (Supported interface modes: * AP), None when unknown."""
    try:
        with open(f'/sys/class/net/{ifname}/phy80211/name') as f:
            phy = f.read().strip()
    except OSError:
        return None
    if not _has(IW):
        return None
    try:
        text = netcfg._run([_which(IW) or IW, 'phy', phy, 'info'], timeout=5)
    except NetError:
        return None
    m = re.search(r'Supported interface modes:\n((?:\s+\* .*\n)+)', text)
    return bool(m and re.search(r'\*\s+AP\s*$', m.group(1), re.M))


def _mode(dev, ap_uuid):
    if ap_uuid and dev.get('uuid') == ap_uuid and dev.get('connected'):
        return 'ap'
    if ap_uuid and dev.get('uuid') == ap_uuid:
        return 'starting'
    return 'client' if dev.get('connected') else 'off'


def status(client_addr=''):
    s = ap_settings()
    devs = [d for d in netcfg.devices() if d['type'] == 'wifi']
    ver = nm_version()
    wifi = []
    for d in devs:
        wifi.append(dict(d, mode=_mode(d, s['uuid']), ap_capable=_ap_capable(d['device'])))
    ap_dev = next((d for d in wifi if d['device'] == s['ifname']), None)
    active = bool(ap_dev and ap_dev['mode'] == 'ap')
    saved = [c for c in netcfg.connections() if c['type'] == 'wifi' and c['uuid'] != s['uuid']]
    return {'settings': s, 'wifi_devices': wifi, 'active': active, 'mode': ap_dev['mode'] if ap_dev else 'off',
            'client_networks': saved, 'reservations': reservations(),
            'clients': clients(s['ifname'])['clients'] if active else [],
            'stations': _has(IW), 'wifi_enabled': netcfg.wifi_enabled(),
            'nm_version': '.'.join(map(str, ver)) if ver else '', 'nm_ok': bool(ver and ver >= MIN_NM),
            'dnsmasq': _has('dnsmasq'), 'client_device': netcfg.client_device(client_addr),
            'pending': netcfg.pending(), 'bands': BANDS, 'channels': CHANNELS, 'lease_range': LEASE_RANGE}


# ── Changes (all under a checkpoint) ───────────────────────────────────────

def _merged(cfg):
    s = ap_settings()
    for k in DEFAULTS:
        if k in cfg:
            s[k] = cfg[k]
    return check_settings(s)


def _install(s, psk, autostart):
    """Write + load the keyfile (and the dnsmasq conf); returns the uuid."""
    s['uuid'] = s.get('uuid') or str(uuidlib.uuid4())
    ensure_dnsmasq_conf()
    _write_private(ap_path(), _keyfile_text(s, psk, autostart))
    netcfg.nm('connection', 'load', ap_path())
    return s['uuid']


def _new_psk(s, password):
    if s['security'] == 'none':
        return ''
    if password:
        return netcfg.check_psk(password)
    old = _psk_from_file()
    if not old:
        raise NetError('Set a Wi-Fi password for the access point (8–63 characters)')
    return old


def save_settings(cfg, password=None):
    """Save the AP / DHCP settings; a running access point is restarted with them (pending change)."""
    s = _merged(cfg)
    psk = _new_psk(s, password)
    old = ap_settings()
    if s['ifname'] != old['ifname'] and old['configured']:
        for d in netcfg.devices():
            if d['device'] == old['ifname'] and d['uuid'] == old['uuid']:
                raise NetError(f'Stop the access point on {old["ifname"]} before moving it to another adapter', 409)
    active = any(d['uuid'] == s['uuid'] and d['connected'] for d in netcfg.devices()) if s['uuid'] else False
    if not active:
        uid = _install(s, psk, old['autostart'] if old['configured'] else False)
        return {'saved': True, 'uuid': uid}

    def run():
        uid = _install(s, psk, True)
        netcfg.nm('connection', 'up', 'uuid', uid, timeout=60)
        return {'uuid': uid}
    return netcfg._guarded(f'Access point {s["ssid"]} settings', run)


def set_mode(mode, ifname='', client_uuid='', cfg=None, password=None):
    """Switch the Wi-Fi adapter between client and access point. ``cfg`` may carry AP settings to save first."""
    if mode not in ('ap', 'client'):
        raise NetError('Mode: ap or client')
    s = ap_settings()
    if mode == 'ap':
        s = _merged(dict(cfg or {}, **({'ifname': ifname} if ifname else {})))
        psk = _new_psk(s, password)

        def run():
            if netcfg.wifi_enabled() is False:
                netcfg.nm('radio', 'wifi', 'on')
            uid = _install(s, psk, True)
            netcfg.nm('connection', 'up', 'uuid', uid, timeout=60)
            return {'uuid': uid, 'mode': 'ap'}
        return netcfg._guarded(f'Access point {s["ssid"]} on {s["ifname"]}', run)

    ifname = ifname or s['ifname']
    netcfg._check_ifname(ifname)
    if client_uuid:
        netcfg._check_uuid(client_uuid)
    psk = _psk_from_file() if s['configured'] else ''

    def run():
        note = ''
        if s['configured']:
            if s['security'] != 'none' and not psk:
                raise NetError('The access point keyfile has no password — save the AP settings first', 409)
            _install(s, psk, False)                                   # no autostart any more
            if any(d['uuid'] == s['uuid'] for d in netcfg.devices()):
                netcfg.nm('connection', 'down', 'uuid', s['uuid'], timeout=30)
        try:
            if client_uuid:
                netcfg.nm('connection', 'up', 'uuid', client_uuid, timeout=60)
            else:
                netcfg.nm('device', 'connect', ifname, timeout=60)
        except NetError as exc:
            if client_uuid:
                raise
            note = f'no known network in range yet ({exc})'
        return {'mode': 'client', 'note': note}
    return netcfg._guarded(f'Wi-Fi client mode on {ifname}', run)


def restart():
    s = ap_settings()
    if not s['configured']:
        raise NetError('The access point is not configured', 404)
    return netcfg._guarded(f'Restart access point {s["ssid"]}',
                           lambda: netcfg.nm('connection', 'up', 'uuid', s['uuid'], timeout=60) and None)


# ── Network map ────────────────────────────────────────────────────────────

def _ip_json(*args):
    try:
        return json.loads(netcfg._run([netcfg.IP, '-j', *args], timeout=5) or '[]')
    except (NetError, ValueError):
        return []


def map_data(client_addr=''):
    """Everything the network map draws: links (all, not only NM ones), routes, AP and its clients."""
    s = ap_settings()
    try:
        nmdevs = {d['device']: d for d in netcfg.devices()}
        conns = {c['uuid']: c for c in netcfg.connections()}
        nm_error = ''
    except NetError as exc:
        nmdevs, conns, nm_error = {}, {}, str(exc)
    links = []
    for l in _ip_json('addr', 'show'):
        name = l.get('ifname', '')
        if not name or name == 'lo':
            continue
        nd = nmdevs.get(name)
        kind = nd['type'] if nd else ('can' if l.get('link_type') == 'can' else
                                      'wifi' if os.path.isdir(f'/sys/class/net/{name}/wireless') else
                                      'ethernet' if l.get('link_type') == 'ether' else l.get('link_type', 'other'))
        link = {'name': name, 'kind': kind, 'state': (l.get('operstate') or '').lower(),
                'up': 'UP' in (l.get('flags') or []) and 'LOWER_UP' in (l.get('flags') or []),
                'mac': l.get('address', ''), 'mtu': l.get('mtu'),
                'ip4': [f'{a["local"]}/{a["prefixlen"]}' for a in l.get('addr_info', []) if a.get('family') == 'inet'],
                'managed': bool(nd)}
        if nd:
            c = conns.get(nd['uuid'], {})
            link.update(connection=nd['connection'], uuid=nd['uuid'], nm_state=nd['state'], connected=nd['connected'],
                        gateway=nd['gateway'], dns=nd['dns'], mode=_mode(nd, s['uuid']) if kind == 'wifi' else '',
                        autoconnect=c.get('autoconnect'))
        links.append(link)
    routes = [{'dev': r.get('dev', ''), 'gateway': r.get('gateway', ''), 'metric': r.get('metric', 0)}
              for r in _ip_json('route', 'show', 'default')]
    routes.sort(key=lambda r: r['metric'] or 0)
    ap = None
    ap_link = next((l for l in links if l['name'] == s['ifname']), None)
    if s['configured']:
        ap = {'ssid': s['ssid'], 'ifname': s['ifname'], 'address': s['address'], 'prefix': s['prefix'],
              'start': s['start'], 'end': s['end'], 'active': bool(ap_link and ap_link.get('mode') == 'ap'),
              'reservations': len(reservations())}
        if ap['active']:
            ap['clients'] = clients(s['ifname'])['clients']
    return {'hostname': os.uname().nodename, 'links': links, 'routes': routes, 'ap': ap, 'nm_error': nm_error,
            'client_device': netcfg.client_device(client_addr), 'pending': netcfg.pending()}
