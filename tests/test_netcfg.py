"""Settings → Network: core/netcfg.py + routes/netcfg.py with a fake nmcli / busctl (netcfg._run is replaced).

Never runs the real nmcli for a change — the board's network must not be touched by tests.
"""
import os
import shutil
import stat
import tempfile
import time
import unittest
from unittest import mock

from tests.support import client  # noqa: F401  (isolates config)
from core import netcfg

WIRED = 'c15cb11d-5fd4-3f65-996b-2b890a3b2c7a'
WIFI = '2778f0d8-5c12-450a-8d38-517392699e15'

DEV_SHOW = """GENERAL.DEVICE:end0
GENERAL.TYPE:ethernet
GENERAL.HWADDR:02:00:83:4C:8E:B3
GENERAL.STATE:100 (connected)
GENERAL.CONNECTION:Wired connection 1
GENERAL.CON-UUID:%s
IP4.ADDRESS[1]:192.168.1.154/24
IP4.GATEWAY:192.168.1.1
IP4.DNS[1]:192.168.1.1
IP6.ADDRESS[1]:fe80::1/64

GENERAL.DEVICE:lo
GENERAL.TYPE:loopback
GENERAL.STATE:100 (connected (externally))

GENERAL.DEVICE:wlan0
GENERAL.TYPE:wifi
GENERAL.HWADDR:9C:3C:76:EF:2D:DE
GENERAL.STATE:30 (disconnected)
GENERAL.CONNECTION:
GENERAL.CON-UUID:
""" % WIRED


class FakeNM:
    def __init__(self, keydir):
        self.calls = []
        self.fail = set()
        self.keydir = keydir
        self.cp = 0

    def conns(self):
        return (f"Wired connection 1:{WIRED}:802-3-ethernet:end0:yes:-999:yes:/run/NetworkManager/system-connections/w.nmconnection\n"
                f"Home\\:Net:{WIFI}:802-11-wireless::yes:5:no:{self.keydir}/home.nmconnection\n"
                "lo:b7eb:loopback:lo:no:0:yes:/run/lo\n")

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        cmd = argv[0]
        for f in self.fail:
            if f in ' '.join(argv):
                raise netcfg.NetError('simulated failure: ' + f)
        if cmd == 'busctl':
            if argv[5] == 'CheckpointCreate':
                self.cp += 1
                return f'o "/org/freedesktop/NetworkManager/Checkpoint/{self.cp}"\n'
            return 'a{su} 0\n' if argv[5] == 'CheckpointRollback' else ''
        if cmd == 'ip':
            return '[{"dst":"%s","dev":"end0"}]' % argv[-1]
        a = argv[1:]
        if a[:2] == ['radio', 'wifi'] and len(a) == 2:
            return 'enabled\n'
        if 'device' in a and 'show' in a:
            return DEV_SHOW
        if a[-2:] == ['connection', 'show']:
            return self.conns()
        if 'connection' in a and 'show' in a and 'uuid' in a:
            return ('connection.id:Wired connection 1\nconnection.type:802-3-ethernet\nconnection.interface-name:end0\n'
                    'connection.autoconnect:yes\nconnection.autoconnect-priority:-999\nipv4.method:manual\n'
                    'ipv4.addresses:192.168.1.154/24, 10.0.0.2/8\nipv4.gateway:192.168.1.1\nipv4.dns:192.168.1.1,8.8.8.8\n'
                    'ipv4.ignore-auto-dns:no\nipv6.method:auto\n')
        if 'wifi' in a and 'list' in a:
            return (" :Office:AA\\:BB:40:WPA2:6:2437 MHz:Infra\n*:Office:AA\\:BC:70:WPA2:44:5220 MHz:Infra\n"
                    " ::AA\\:BD:90:WPA2:1:2412 MHz:Infra\n :Cafe:AA\\:BE:55::11:2462 MHz:Infra\n")
        return ''


def read(path):
    with open(path) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.keydir = tempfile.mkdtemp(prefix='smms-nm-')
        self.fake = FakeNM(self.keydir)
        self.patches = [mock.patch.object(netcfg, '_run', self.fake),
                        mock.patch.object(netcfg, 'KEYFILE_DIR', self.keydir)]
        for p in self.patches:
            p.start()
        netcfg._pending = netcfg._last = None

    def tearDown(self):
        for p in self.patches:
            p.stop()
        netcfg._pending = netcfg._last = None
        shutil.rmtree(self.keydir, ignore_errors=True)

    def nm_calls(self):
        return [c[1:] for c in self.fake.calls if c[0] == 'nmcli']

    def bus_calls(self):
        return [c[5] for c in self.fake.calls if c[0] == 'busctl']


class Read(Base):
    def test_split_terse(self):
        self.assertEqual(netcfg.split_terse(r'a\:b:c\\d::e'), ['a:b', 'c\\d', '', 'e'])

    def test_overview(self):
        o = netcfg.overview('192.168.1.50')
        self.assertEqual([d['device'] for d in o['devices']], ['end0', 'wlan0'])
        self.assertEqual(o['devices'][0]['ip4'], ['192.168.1.154/24'])
        self.assertFalse(o['devices'][1]['connected'])
        self.assertEqual([c['name'] for c in o['connections']], ['Wired connection 1', 'Home:Net'])
        self.assertEqual(o['client_device'], 'end0')
        self.assertTrue(o['wifi_enabled'])

    def test_connection_and_scan(self):
        c = netcfg.connection(WIRED)
        self.assertEqual(c['ipv4']['addresses'], ['192.168.1.154/24', '10.0.0.2/8'])
        self.assertEqual(c['ipv4']['dns'], ['192.168.1.1', '8.8.8.8'])
        nets = netcfg.scan()
        self.assertEqual([n['ssid'] for n in nets], ['Office', 'Cafe'])          # hidden SSID dropped, one row per SSID
        self.assertTrue(nets[0]['in_use'])
        self.assertEqual(nets[1]['security'], 'open')
        with self.assertRaises(netcfg.NetError):
            netcfg.connection('x; rm -rf /')


class Changes(Base):
    def test_static_ip_is_pending_until_confirmed(self):
        p = netcfg.save_connection(WIRED, {'ipv4': {'method': 'manual', 'addresses': ['192.168.1.60/24'],
                                                    'gateway': '192.168.1.1', 'dns': ['1.1.1.1']}, 'priority': 5})
        self.assertEqual(p['label'], 'Change Wired connection 1')
        mod = next(c for c in self.nm_calls() if c[:2] == ['connection', 'modify'])
        self.assertIn('192.168.1.60/24', mod)
        self.assertEqual(mod[mod.index('ipv4.gateway') + 1], '192.168.1.1')
        self.assertEqual(mod[mod.index('connection.autoconnect-priority') + 1], '5')
        self.assertIn(['connection', 'up', 'uuid', WIRED], self.nm_calls())          # active -> re-applied
        self.assertEqual(self.bus_calls(), ['CheckpointCreate'])
        with self.assertRaises(netcfg.NetError) as cm:
            netcfg.activate(WIFI)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(netcfg.confirm()['last']['result'], 'kept')
        self.assertEqual(self.bus_calls(), ['CheckpointCreate', 'CheckpointDestroy'])
        self.assertIsNone(netcfg._pending)

    def test_dhcp_clears_static_fields(self):
        netcfg.save_connection(WIRED, {'ipv4': {'method': 'auto', 'addresses': ['1.2.3.4/24'], 'gateway': '1.2.3.1'}})
        mod = next(c for c in self.nm_calls() if c[:2] == ['connection', 'modify'])
        self.assertEqual(mod[mod.index('ipv4.addresses') + 1], '')
        self.assertEqual(mod[mod.index('ipv4.gateway') + 1], '')

    def test_failure_rolls_back_at_once(self):
        self.fake.fail.add('connection up')
        with self.assertRaises(netcfg.NetError):
            netcfg.activate(WIFI)
        self.assertEqual(self.bus_calls(), ['CheckpointCreate', 'CheckpointRollback'])
        self.assertIsNone(netcfg.pending())

    def test_timeout_means_rolled_back(self):
        netcfg.set_wifi(False)
        netcfg._pending['deadline'] = time.time() - 10
        self.assertIn('rolled back', netcfg.pending()['last']['result'])
        self.assertEqual(self.fake.calls[-1][:2], ['nmcli', 'radio'])

    def test_revert(self):
        netcfg.deactivate(WIRED)
        self.assertEqual(netcfg.revert()['last']['result'], 'reverted')
        self.assertEqual(self.bus_calls()[-1], 'CheckpointRollback')

    def test_validation(self):
        for cfg in ({'ipv4': {'method': 'manual', 'addresses': []}}, {'ipv4': {'method': 'manual', 'addresses': ['300.1.1.1/24']}},
                    {'ipv4': {'method': 'auto', 'dns': ['nope']}}, {'ipv4': {'method': 'bogus'}}, {'priority': 5000},
                    {'interface': 'eth0; reboot'}, {'ipv6': {'method': 'x'}}):
            with self.subTest(cfg=cfg), self.assertRaises(netcfg.NetError):
                netcfg.save_connection(WIRED, cfg)
        self.assertEqual(self.bus_calls(), [])                                        # nothing applied
        for bad in ('short', 'é' * 10, 'x' * 64):
            with self.subTest(psk=bad), self.assertRaises(netcfg.NetError):
                netcfg.check_psk(bad)
        self.assertEqual(netcfg.check_psk('f' * 64), 'f' * 64)

    def test_join_new_network_keeps_password_off_the_command_line(self):
        netcfg.wifi_connect('Office', 's3cret-pass\\x', 'wlan0', 'WPA2')
        files = os.listdir(self.keydir)
        self.assertEqual(len(files), 1)
        path = os.path.join(self.keydir, files[0])
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        text = read(path)
        self.assertIn('ssid=Office', text)
        self.assertIn('psk=s3cret-pass\\\\x', text)
        self.assertIn('key-mgmt=wpa-psk', text)
        for c in self.fake.calls:
            self.assertFalse(any('s3cret' in a for a in c))
        self.assertEqual([c[:2] for c in self.nm_calls() if c[0] == 'connection' and c[1] in ('load', 'up')],
                         [['connection', 'load'], ['connection', 'up']])

    def test_join_failure_removes_profile(self):
        self.fake.fail.add('connection up')
        with self.assertRaises(netcfg.NetError):
            netcfg.wifi_connect('Office', 'password1', 'wlan0')
        self.assertTrue(any(c[:2] == ['connection', 'delete'] for c in self.nm_calls()))

    def test_new_password_of_saved_network(self):
        path = os.path.join(self.keydir, 'home.nmconnection')
        with open(path, 'w') as f:
            f.write('[connection]\nid=Home:Net\n\n[wifi-security]\nkey-mgmt=wpa-psk\npsk=oldpassword\n\n[ipv4]\nmethod=auto\n')
        netcfg.save_connection(WIFI, {'autoconnect': True}, password='newpassword')
        text = read(path)
        self.assertIn('psk=newpassword\n', text)
        self.assertNotIn('oldpassword', text)
        self.assertIn('[ipv4]', text)
        self.assertIn(['connection', 'load', path], self.nm_calls())

    def test_hotspot(self):
        netcfg.hotspot('Board', 'password1', 'wlan0')
        text = read(os.path.join(self.keydir, os.listdir(self.keydir)[0]))
        self.assertIn('mode=ap', text)
        self.assertIn('method=shared', text)
        with self.assertRaises(netcfg.NetError):
            netcfg.hotspot('Board', 'short', 'wlan0')


class Routes(Base):
    def test_api(self):
        c = client(logged_in=True)
        self.assertEqual(c.get('/api/netcfg').get_json()['devices'][0]['device'], 'end0')
        self.assertEqual(c.get('/api/netcfg/wifi').get_json()['networks'][0]['ssid'], 'Office')
        r = c.post('/api/netcfg/connection', json={'uuid': WIRED, 'ipv4': {'method': 'manual', 'addresses': ['bad']}})
        self.assertEqual(r.status_code, 400)
        r = c.post('/api/netcfg/activate', json={'uuid': WIFI})
        self.assertEqual(r.status_code, 200)
        self.assertIn('left', r.get_json())
        self.assertEqual(c.post('/api/netcfg/activate', json={'uuid': WIFI}).status_code, 409)
        self.assertEqual(c.post('/api/netcfg/confirm', json={}).status_code, 200)
        self.assertEqual(c.post('/api/netcfg/nope', json={}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
