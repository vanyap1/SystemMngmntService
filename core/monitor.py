"""System monitor for the dashboard: CPU, memory, temperature, active network interface, block devices.

A sampler thread reads /proc and /sys once per second and keeps a short history for the charts.
It runs only while somebody polls `snapshot()` (lease), like the other background resources.
"""
import glob
import json
import os
import socket
import struct
import threading
import time
from collections import deque

from core.shell import quote, sh

INTERVAL = 1.0           # seconds between samples
HISTORY = 900            # samples kept (15 minutes)
LEASE_SECONDS = 30
LSBLK_TTL = 5            # lsblk is a subprocess: cache it
SECTOR = 512             # /proc/diskstats always counts 512-byte sectors
SKIP_BLOCK = ('loop', 'ram')


def _read(path, default=''):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError):
        return default


def _int(path):
    try:
        return int(_read(path))
    except ValueError:
        return None


# ── raw readers ──────────────────────────────────────────────────────────

def _cpu_times():
    """{'cpu': (busy, total), 'cpu0': ...} from /proc/stat."""
    out = {}
    for line in _read('/proc/stat').split('\n'):
        if not line.startswith('cpu'):
            break
        p = line.split()
        v = [int(x) for x in p[1:9]]
        idle = v[3] + v[4]                       # idle + iowait
        out[p[0]] = (sum(v) - idle, sum(v))
    return out


def _meminfo():
    m = {}
    for line in _read('/proc/meminfo').split('\n'):
        p = line.split()
        if len(p) >= 2:
            m[p[0].rstrip(':')] = int(p[1]) * 1024
    total = m.get('MemTotal', 0)
    avail = m.get('MemAvailable', m.get('MemFree', 0))
    st, sf = m.get('SwapTotal', 0), m.get('SwapFree', 0)
    return {
        'total': total, 'used': total - avail, 'avail': avail,
        'cached': m.get('Cached', 0) + m.get('Buffers', 0) + m.get('SReclaimable', 0),
        'pct': round((total - avail) * 100 / total, 1) if total else 0,
        'swap_total': st, 'swap_used': st - sf,
        'swap_pct': round((st - sf) * 100 / st, 1) if st else 0,
    }


def _sensors():
    """All thermal zones as [{name, temp °C}]; the CPU one first."""
    out = []
    for zone in sorted(glob.glob('/sys/class/thermal/thermal_zone*')):
        t = _int(zone + '/temp')
        if t is not None and t > -40000:
            out.append({'name': _read(zone + '/type') or os.path.basename(zone), 'temp': round(t / 1000, 1)})
    if not out:                                  # x86 without thermal zones: coretemp / k10temp
        for hw in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
            name = _read(hw + '/name')
            t = _int(hw + '/temp1_input')
            if t is not None and name in ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'soc_thermal'):
                out.append({'name': name, 'temp': round(t / 1000, 1)})
    out.sort(key=lambda s: 0 if any(k in s['name'].lower() for k in ('cpu', 'soc', 'core', 'k10', 'x86_pkg')) else 1)
    return out


def _cpu_freq():
    f = [_int(p) for p in glob.glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq')]
    f = [x for x in f if x]
    return round(max(f) / 1000) if f else None


def _default_iface():
    """(iface, gateway) of the default route with the lowest metric, from /proc/net/route."""
    best = None
    for line in _read('/proc/net/route').split('\n')[1:]:
        p = line.split()
        if len(p) >= 8 and p[1] == '00000000' and int(p[3], 16) & 1:
            metric = int(p[6])
            if best is None or metric < best[2]:
                gw = socket.inet_ntoa(struct.pack('<I', int(p[2], 16)))
                best = (p[0], gw, metric)
    if best:
        return best[0], best[1]
    for name in sorted(os.listdir('/sys/class/net')):   # no default route: first link that is up
        if name != 'lo' and _read(f'/sys/class/net/{name}/operstate') == 'up':
            return name, ''
    return None, ''


def _net_counters(iface):
    base = f'/sys/class/net/{iface}/statistics/'
    return {k: _int(base + k) or 0 for k in ('rx_bytes', 'tx_bytes', 'rx_packets', 'tx_packets',
                                            'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped')}


def _diskstats():
    """{name: (read_bytes, write_bytes, io_ms)}"""
    out = {}
    for line in _read('/proc/diskstats').split('\n'):
        p = line.split()
        if len(p) >= 13 and not p[2].startswith(SKIP_BLOCK):
            out[p[2]] = (int(p[5]) * SECTOR, int(p[9]) * SECTOR, int(p[12]))
    return out


def _rate(new, old, dt):
    return max(0, (new - old) / dt) if dt > 0 else 0


# ── sampler ──────────────────────────────────────────────────────────────

class Monitor:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._seen = 0.0
        self.history = deque(maxlen=HISTORY)    # [t, cpu %, mem %, rx B/s, tx B/s, temp °C]
        self.current = {}
        self._lsblk = (0.0, [])

    def _ensure(self):
        self._seen = time.monotonic()
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name='monitor', daemon=True)
                self._thread.start()

    def _run(self):
        prev = None
        while time.monotonic() - self._seen < LEASE_SECONDS:
            now = time.time()
            cur = {'t': now, 'cpu': _cpu_times(), 'disk': _diskstats()}
            iface, gw = _default_iface()
            cur['iface'], cur['gateway'] = iface, gw
            cur['net'] = _net_counters(iface) if iface else {}
            if prev:
                self._sample(prev, cur)
            prev = cur
            time.sleep(max(0.1, INTERVAL - (time.time() - now)))
        with self._lock:
            self._thread = None

    def _sample(self, prev, cur):
        dt = cur['t'] - prev['t']
        cores = []
        for name, (busy, total) in cur['cpu'].items():
            pb, pt = prev['cpu'].get(name, (busy, total))
            pct = round((busy - pb) * 100 / (total - pt), 1) if total > pt else 0.0
            cores.append((name, pct))
        cpu_pct = cores[0][1] if cores else 0.0
        mem = _meminfo()
        sensors = _sensors()
        temp = sensors[0]['temp'] if sensors else None

        net = {'iface': cur['iface'], 'gateway': cur['gateway'], 'rx_rate': 0, 'tx_rate': 0}
        if cur['iface']:
            net.update(cur['net'])
            if prev['iface'] == cur['iface']:
                net['rx_rate'] = _rate(cur['net']['rx_bytes'], prev['net']['rx_bytes'], dt)
                net['tx_rate'] = _rate(cur['net']['tx_bytes'], prev['net']['tx_bytes'], dt)

        disk = {}
        for name, (rb, wb, ms) in cur['disk'].items():
            p = prev['disk'].get(name)
            if p:
                disk[name] = {'read_rate': _rate(rb, p[0], dt), 'write_rate': _rate(wb, p[1], dt),
                              'busy': min(100, round(_rate(ms, p[2], dt) / 10, 1))}

        la = _read('/proc/loadavg').split()
        self.current = {
            'cpu': {'pct': cpu_pct, 'cores': [c[1] for c in cores[1:]], 'count': len(cores) - 1,
                    'load': la[:3], 'freq_mhz': _cpu_freq()},
            'mem': mem, 'temp': temp, 'sensors': sensors, 'net': net, 'disk': disk,
            'procs': la[3].split('/')[1] if len(la) > 3 and '/' in la[3] else '',
        }
        self.history.append([round(cur['t'], 2), cpu_pct, mem['pct'],
                             round(net['rx_rate']), round(net['tx_rate']), temp])

    # ── data for the API ──

    def _block_devices(self):
        ts, cached = self._lsblk
        if time.monotonic() - ts < LSBLK_TTL:
            return cached
        try:
            tree = json.loads(sh('lsblk -J -b -o NAME,SIZE,TYPE,RO,RM,TRAN,MODEL,FSTYPE,MOUNTPOINTS,'
                                 'FSSIZE,FSUSED', timeout=5) or '{}').get('blockdevices', [])
        except ValueError:
            tree = []
        swaps = {}
        for line in _read('/proc/swaps').split('\n')[1:]:
            p = line.split()
            if len(p) >= 4:
                swaps[os.path.basename(p[0])] = (int(p[2]) * 1024, int(p[3]) * 1024)

        def node(d):
            name = d.get('name', '')
            mounts = [m for m in (d.get('mountpoints') or []) if m]
            size, used = d.get('fssize'), d.get('fsused')
            if name in swaps:
                size, used = swaps[name]
            item = {'name': name, 'size': d.get('size') or 0, 'type': d.get('type', ''),
                    'ro': bool(d.get('ro')), 'rm': bool(d.get('rm')), 'tran': d.get('tran') or '',
                    'model': (d.get('model') or '').strip(), 'fstype': d.get('fstype') or '',
                    'mounts': mounts, 'fssize': int(size) if size else None, 'fsused': int(used) if used else 0,
                    'children': [node(c) for c in d.get('children') or []]}
            if item['type'] == 'disk':
                t = [_int(p) for p in glob.glob(f'/sys/block/{name}/device/hwmon*/temp1_input') +
                     glob.glob(f'/sys/block/{name}/device/device/hwmon*/temp1_input')]
                item['temp'] = round(t[0] / 1000, 1) if t and t[0] is not None else None
            return item

        out = [node(d) for d in tree
               if not d.get('name', '').startswith(SKIP_BLOCK) and (d.get('size') or 0) > 0]
        self._lsblk = (time.monotonic(), out)
        return out

    def _iface_info(self, iface):
        if not iface:
            return {}
        base = f'/sys/class/net/{iface}'
        addrs = []
        try:
            for link in json.loads(sh(f'ip -j addr show dev {quote(iface)}', timeout=3) or '[]'):
                addrs += [f"{a.get('local')}/{a.get('prefixlen')}" for a in link.get('addr_info', [])]
        except ValueError:
            pass
        speed = _int(base + '/speed') if _read(base + '/operstate') == 'up' else None
        return {'operstate': _read(base + '/operstate'), 'carrier': _read(base + '/carrier') == '1',
                'mac': _read(base + '/address'), 'mtu': _int(base + '/mtu'),
                'speed': speed if speed and speed > 0 else None,
                'wireless': os.path.isdir(base + '/wireless'), 'addrs': addrs}

    def snapshot(self, since=0.0):
        """Current values + history newer than `since`; also renews the sampler lease."""
        self._ensure()
        cur = dict(self.current)
        if cur.get('net'):
            cur['net'] = {**cur['net'], **self._iface_info(cur['net'].get('iface'))}
        uptime = _read('/proc/uptime').split()
        return {
            'now': time.time(), 'interval': INTERVAL,
            'uptime': float(uptime[0]) if uptime else None,
            'hostname': socket.gethostname(),
            'current': cur,
            'blocks': self._block_devices(),
            'history': [h for h in list(self.history) if h[0] > since],
        }


monitor = Monitor()
