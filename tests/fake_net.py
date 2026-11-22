"""Simulated NetworkManager / iw / ip for core/netcfg.py + core/netap.py (tests and ``devserver.py --fake-net``).

``FakeNet(root)`` replaces ``netcfg._run`` and keeps state: a wired uplink, a Wi-Fi adapter that is either a client
of "Office" or the access point (the keyfile netap writes into ``root``), DHCP leases and associated stations.
Paths of netap / netcfg are pointed into ``root`` by ``install()``. Nothing here touches the real network.
"""
import json
import os
import re
import time
from unittest import mock

from core import netap, netcfg

WIRED = 'c15cb11d-5fd4-3f65-996b-2b890a3b2c7a'
OFFICE = '2778f0d8-5c12-450a-8d38-517392699e15'
CLIENTS = [('aa:bb:cc:00:00:01', '10.10.10.23', 'phone', -48), ('aa:bb:cc:00:00:02', '10.10.10.57', 'scope', -63),
           ('aa:bb:cc:00:00:03', '10.10.10.88', '*', None)]


class FakeNet:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.fail = set()
        self.cp = 0
        self.wifi_conn = OFFICE           # uuid active on wlan0 ('' = disconnected)
        self.radio = True

    # ── state helpers ──
    def ap_uuid(self):
        try:
            with open(netap.ap_path()) as f:
                m = re.search(r'^uuid=(.+)$', f.read(), re.M)
                return m.group(1) if m else ''
        except OSError:
            return ''

    def _dev_show(self):
        wifi_up = bool(self.wifi_conn)
        ap = wifi_up and self.wifi_conn == self.ap_uuid()
        name = 'SMMS Access Point' if ap else 'Office' if wifi_up else ''
        ip = '10.10.10.1/24' if ap else '192.168.1.77/24' if wifi_up else ''
        return ('GENERAL.DEVICE:end0\nGENERAL.TYPE:ethernet\nGENERAL.HWADDR:02:00:83:4C:8E:B3\nGENERAL.STATE:100 (connected)\n'
                f'GENERAL.CONNECTION:Wired connection 1\nGENERAL.CON-UUID:{WIRED}\nIP4.ADDRESS[1]:192.168.1.154/24\n'
                'IP4.GATEWAY:192.168.1.1\nIP4.DNS[1]:192.168.1.1\n\n'
                'GENERAL.DEVICE:wlan0\nGENERAL.TYPE:wifi\nGENERAL.HWADDR:9C:3C:76:EF:2D:DE\n'
                f'GENERAL.STATE:{"100 (connected)" if wifi_up else "30 (disconnected)"}\nGENERAL.CONNECTION:{name}\n'
                f'GENERAL.CON-UUID:{self.wifi_conn}\n' + (f'IP4.ADDRESS[1]:{ip}\n' if ip else '') +
                ('IP4.GATEWAY:192.168.1.1\n' if wifi_up and not ap else ''))

    def _conns(self):
        out = (f"Wired connection 1:{WIRED}:802-3-ethernet:end0:yes:-999:yes:/run/w.nmconnection\n"
               f"Office:{OFFICE}:802-11-wireless:{'wlan0' if self.wifi_conn == OFFICE else ''}:yes:0:"
               f"{'yes' if self.wifi_conn == OFFICE else 'no'}:{self.root}/office.nmconnection\n")
        ap = self.ap_uuid()
        if ap:
            act = self.wifi_conn == ap
            out += f"SMMS Access Point:{ap}:802-11-wireless:{'wlan0' if act else ''}:yes:100:{'yes' if act else 'no'}:{netap.ap_path()}\n"
        return out

    def _ip(self, a):
        ap = self.wifi_conn and self.wifi_conn == self.ap_uuid()
        if a[:2] == ['route', 'get']:
            return json.dumps([{'dst': a[-1], 'dev': 'wlan0' if a[-1].startswith('10.10.10.') else 'end0'}])
        if a[:2] == ['route', 'show']:
            r = [{'dst': 'default', 'gateway': '192.168.1.1', 'dev': 'end0', 'metric': 100}]
            if self.wifi_conn == OFFICE:
                r.append({'dst': 'default', 'gateway': '192.168.1.1', 'dev': 'wlan0', 'metric': 600})
            return json.dumps(r)
        if a[:2] == ['addr', 'show']:
            wl = [] if not self.wifi_conn else [{'family': 'inet', 'local': '10.10.10.1' if ap else '192.168.1.77', 'prefixlen': 24}]
            return json.dumps([
                {'ifname': 'lo', 'link_type': 'loopback', 'flags': ['UP', 'LOWER_UP'], 'operstate': 'UNKNOWN', 'addr_info': []},
                {'ifname': 'end0', 'link_type': 'ether', 'flags': ['UP', 'LOWER_UP'], 'operstate': 'UP', 'address': '02:00:83:4c:8e:b3',
                 'mtu': 1500, 'addr_info': [{'family': 'inet', 'local': '192.168.1.154', 'prefixlen': 24}]},
                {'ifname': 'wlan0', 'link_type': 'ether', 'flags': ['UP', 'LOWER_UP'] if self.wifi_conn else ['UP'],
                 'operstate': 'UP' if self.wifi_conn else 'DOWN', 'address': '9c:3c:76:ef:2d:de', 'mtu': 1500, 'addr_info': wl},
                {'ifname': 'can0', 'link_type': 'can', 'flags': ['NOARP'], 'operstate': 'DOWN', 'mtu': 16, 'addr_info': []},
                {'ifname': 'usb0', 'link_type': 'ether', 'flags': ['UP', 'LOWER_UP'], 'operstate': 'UP', 'address': '32:1e:31:f9:c2:f8',
                 'mtu': 1500, 'addr_info': [{'family': 'inet', 'local': '172.16.5.1', 'prefixlen': 24}]},
            ])
        if a[:2] == ['neigh', 'show']:
            return json.dumps([{'dst': ip, 'lladdr': mac, 'state': ['REACHABLE']} for mac, ip, _, _ in CLIENTS[:2]] if ap else [])
        return '[]'

    def _iw(self, a):
        if a[:1] == ['phy']:
            return 'Wiphy phy0\n\tSupported interface modes:\n\t\t * managed\n\t\t * AP\n\t\t * monitor\n\tBand 1:\n'
        if a[-2:] == ['station', 'dump'] and self.wifi_conn and self.wifi_conn == self.ap_uuid():
            return ''.join(f'Station {mac} (on wlan0)\n\tinactive time:\t120 ms\n\trx bytes:\t{10000 * (i + 1)}\n'
                           f'\ttx bytes:\t{52000 * (i + 1)}\n\tsignal:  \t{sig} [{sig}, {sig}] dBm\n'
                           f'\ttx bitrate:\t72.2 MBit/s MCS 7 short GI\n\tconnected time:\t{340 * (i + 1)} seconds\n'
                           for i, (mac, _, _, sig) in enumerate(CLIENTS) if sig is not None)
        return ''

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        for f in self.fail:
            if f in ' '.join(argv):
                raise netcfg.NetError('simulated failure: ' + f)
        cmd, a = os.path.basename(argv[0]), argv[1:]
        if cmd == 'busctl':
            if argv[5] == 'CheckpointCreate':
                self.cp += 1
                return f'o "/org/freedesktop/NetworkManager/Checkpoint/{self.cp}"\n'
            return ''
        if cmd == 'ip':
            return self._ip(a[1:])
        if cmd == 'iw':
            return self._iw(a)
        if a == ['--version']:
            return 'nmcli tool, version 1.42.4\n'
        if a[:2] == ['radio', 'wifi']:
            if len(a) == 3:
                self.radio = a[2] == 'on'
                return ''
            return 'enabled\n' if self.radio else 'disabled\n'
        if 'device' in a and 'show' in a:
            return self._dev_show()
        if a[-2:] == ['connection', 'show']:
            return self._conns()
        if a[:3] == ['connection', 'up', 'uuid']:
            self.wifi_conn = a[3] if a[3] in (OFFICE, self.ap_uuid()) else self.wifi_conn
            return ''
        if a[:3] == ['connection', 'down', 'uuid']:
            if self.wifi_conn == a[3]:
                self.wifi_conn = ''
            return ''
        if a[:2] == ['device', 'connect']:
            self.wifi_conn = OFFICE
            return ''
        if 'wifi' in a and 'list' in a:
            return '*:Office:AA\\:BC:70:WPA2:44:5220 MHz:Infra\n :Cafe:AA\\:BE:55::11:2462 MHz:Infra\n'
        return ''


def install(root):
    """Point netcfg / netap at ``root`` and a FakeNet; returns (fake, patches started)."""
    fake = FakeNet(root)
    leases = os.path.join(root, 'dnsmasq-{ifname}.leases')
    with open(leases.format(ifname='wlan0'), 'w') as f:
        f.write(''.join(f'{int(time.time()) + 1800 * (i + 1)} {mac} {ip} {host} *\n' for i, (mac, ip, host, _) in enumerate(CLIENTS)))
    patches = [mock.patch.object(netcfg, '_run', fake), mock.patch.object(netcfg, 'KEYFILE_DIR', os.path.join(root, 'nm')),
               mock.patch.object(netap, 'DNSMASQ_DIR', os.path.join(root, 'dnsmasq-shared.d')),
               mock.patch.object(netap, 'HOSTS_FILE', os.path.join(root, 'smms-dhcp.hosts')),
               mock.patch.object(netap, 'LEASES', leases),
               mock.patch.object(netap, 'PIDFILE', os.path.join(root, 'nm-dnsmasq-{ifname}.pid')),
               mock.patch.object(netap, '_has', lambda cmd: True),
               mock.patch.object(netap, '_ap_capable', lambda ifname: True if ifname == 'wlan0' else None)]
    for p in patches:
        p.start()
    return fake, patches
