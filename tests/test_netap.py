"""Settings → Network → Access point & DHCP and the network map (core/netap.py) with tests/fake_net.py.

Never runs the real nmcli / iw and never writes into /etc — every path points into a temp dir.
"""
import os
import shutil
import signal
import stat
import tempfile
import unittest
from unittest import mock

from tests.support import client  # noqa: F401  (isolates config)
from tests import fake_net
from core import netap, netcfg

AP = {'ssid': 'Bench-AP', 'ifname': 'wlan0'}


def read(path):
    with open(path) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='smms-ap-')
        self.fake, self.patches = fake_net.install(self.root)
        netcfg._pending = netcfg._last = None

    def tearDown(self):
        for p in self.patches:
            p.stop()
        netcfg._pending = netcfg._last = None
        shutil.rmtree(self.root, ignore_errors=True)

    def nm_calls(self):
        return [c[1:] for c in self.fake.calls if c[0] == 'nmcli']

    def bus(self):
        return [c[5] for c in self.fake.calls if c[0] == 'busctl']

    def start_ap(self, **kw):
        p = netap.set_mode('ap', 'wlan0', cfg=dict(AP, **kw), password='bench-pass-1')
        netcfg.confirm()
        return p


class Settings(Base):
    def test_defaults(self):
        s = netap.ap_settings()
        self.assertFalse(s['configured'])
        self.assertEqual((s['address'], s['prefix'], s['start'], s['end']), ('10.10.10.1', 24, '10.10.10.2', '10.10.10.254'))

    def test_save_inactive_writes_keyfile_without_checkpoint(self):
        r = netap.save_settings(dict(AP, lease=600), 'bench-pass-1')
        self.assertTrue(r['saved'])
        self.assertEqual(self.bus(), [])                                         # nothing on the link changed
        path = netap.ap_path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        text = read(path)
        for line in ('mode=ap', 'ssid=Bench-AP', 'method=shared', 'address1=10.10.10.1/24',
                     'shared-dhcp-range=10.10.10.2,10.10.10.254', 'shared-dhcp-lease-time=600', 'autoconnect=false',
                     'interface-name=wlan0', 'psk=bench-pass-1'):
            self.assertIn(line + '\n', text)
        for c in self.fake.calls:
            self.assertFalse(any('bench-pass' in a for a in c))                  # password never on a command line
        s = netap.ap_settings()
        self.assertTrue(s['configured'] and s['has_password'])
        self.assertEqual(s['lease'], 600)
        self.assertNotIn('psk', s)
        conf = read(os.path.join(netap.DNSMASQ_DIR, netap.CONF_NAME))
        self.assertIn(f'dhcp-hostsfile={netap.HOSTS_FILE}', conf)

    def test_password_kept_and_required(self):
        with self.assertRaises(netcfg.NetError):
            netap.save_settings(AP)                                              # new AP without a password
        netap.save_settings(AP, 'bench-pass-1')
        netap.save_settings(dict(AP, ssid='Other'))                              # empty password = keep
        self.assertIn('psk=bench-pass-1\n', read(netap.ap_path()))
        netap.save_settings(dict(AP, security='none'))
        self.assertNotIn('psk=', read(netap.ap_path()))

    def test_validation(self):
        bad = [{'address': '10.10.10.0'}, {'address': '8.8.8.1'}, {'start': '10.10.11.2'}, {'start': '10.10.10.200', 'end': '10.10.10.100'},
               {'start': '10.10.10.1'}, {'lease': 10}, {'prefix': 31}, {'band': 'x'}, {'channel': 36}, {'ifname': 'wl;0'},
               {'ssid': ''}, {'end': '10.10.10.255'}]
        for b in bad:
            with self.subTest(b=b), self.assertRaises(netcfg.NetError):
                netap.save_settings(dict(AP, **b), 'bench-pass-1')
        s = netap.check_settings(dict(netap.DEFAULTS, ssid='x', ifname='wlan0', address='192.168.50.1', start='192.168.50.100',
                                      end='192.168.50.199', band='a', channel=36))
        self.assertEqual(s['channel'], 36)


class Mode(Base):
    def test_switch_to_ap_and_back(self):
        p = netap.set_mode('ap', 'wlan0', cfg=AP, password='bench-pass-1')
        self.assertIn('Access point Bench-AP', p['label'])
        self.assertEqual(self.bus(), ['CheckpointCreate'])
        self.assertIn('autoconnect=true\n', read(netap.ap_path()))               # comes back after a reboot
        uid = netap.ap_settings()['uuid']
        self.assertIn(['connection', 'up', 'uuid', uid], self.nm_calls())
        netcfg.confirm()
        st = netap.status('10.10.10.23')
        self.assertTrue(st['active'])
        self.assertEqual(st['mode'], 'ap')
        self.assertEqual(st['client_device'], 'wlan0')
        self.assertEqual(len(st['clients']), 3)

        p = netap.set_mode('client', 'wlan0')
        self.assertEqual(p['result']['mode'], 'client')
        self.assertIn('autoconnect=false\n', read(netap.ap_path()))
        self.assertIn(['connection', 'down', 'uuid', uid], self.nm_calls())
        self.assertIn(['device', 'connect', 'wlan0'], self.nm_calls())
        netcfg.confirm()
        self.assertEqual(netap.status()['mode'], 'client')

    def test_client_to_saved_network_and_failure_rolls_back(self):
        self.start_ap()
        self.fake.fail.add('connection up uuid ' + fake_net.OFFICE)
        with self.assertRaises(netcfg.NetError):
            netap.set_mode('client', 'wlan0', fake_net.OFFICE)
        self.assertEqual(self.bus()[-1], 'CheckpointRollback')
        self.fake.fail.clear()
        self.fake.fail.add('device connect')                                     # nothing known in range: kept, with a note
        p = netap.set_mode('client', 'wlan0')
        self.assertIn('no known network', p['result']['note'])

    def test_radio_switched_on_for_ap(self):
        self.fake.radio = False
        netap.set_mode('ap', 'wlan0', cfg=AP, password='bench-pass-1')
        self.assertIn(['radio', 'wifi', 'on'], self.nm_calls())

    def test_save_while_active_is_pending(self):
        self.start_ap()
        p = netap.save_settings({'address': '10.20.0.1', 'start': '10.20.0.10', 'end': '10.20.0.50'})
        self.assertIn('path', p)
        self.assertIn('shared-dhcp-range=10.20.0.10,10.20.0.50\n', read(netap.ap_path()))
        netcfg.revert()

    def test_bad_mode(self):
        with self.assertRaises(netcfg.NetError):
            netap.set_mode('mesh', 'wlan0')


class Dhcp(Base):
    def test_reservations(self):
        netap.save_settings(AP, 'bench-pass-1')
        r = netap.set_reservations([{'mac': 'AA-BB-CC-00-00-02', 'ip': '10.10.10.5', 'name': 'scope'},
                                    {'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.3'}])
        self.assertEqual([x['ip'] for x in r['reservations']], ['10.10.10.3', '10.10.10.5'])
        text = read(netap.HOSTS_FILE)
        self.assertIn('aa:bb:cc:00:00:02,10.10.10.5,scope\n', text)
        self.assertEqual(netap.reservations()[1], {'mac': 'aa:bb:cc:00:00:02', 'ip': '10.10.10.5', 'name': 'scope'})
        self.assertFalse(r['reloaded'])                                          # no dnsmasq running

    def test_reservation_validation(self):
        netap.save_settings(AP, 'bench-pass-1')
        for bad in ([{'mac': 'zz', 'ip': '10.10.10.5'}], [{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.11.5'}],
                    [{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.1'}], [{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.255'}],
                    [{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.5'}, {'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.6'}],
                    [{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.5'}, {'mac': 'aa:bb:cc:00:00:02', 'ip': '10.10.10.5'}],
                    [{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.5', 'name': 'bad name\nx'}], 'nope'):
            with self.subTest(bad=bad), self.assertRaises(netcfg.NetError):
                netap.set_reservations(bad)

    def test_sighup_reloads_running_dnsmasq(self):
        netap.save_settings(AP, 'bench-pass-1')
        with open(netap.PIDFILE.format(ifname='wlan0'), 'w') as f:
            f.write('4242\n')
        with mock.patch.object(netap, '_dnsmasq_pid', return_value=4242), mock.patch.object(netap.os, 'kill') as kill:
            r = netap.set_reservations([{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.9'}])
        kill.assert_called_once_with(4242, signal.SIGHUP)
        self.assertTrue(r['reloaded'])

    def test_clients_join_leases_stations_reservations(self):
        self.start_ap()
        netap.set_reservations([{'mac': 'aa:bb:cc:00:00:02', 'ip': '10.10.10.57', 'name': 'scope-1'}])
        cl = {c['mac']: c for c in netap.clients()['clients']}
        self.assertEqual(cl['aa:bb:cc:00:00:01']['signal'], -48)
        self.assertEqual(cl['aa:bb:cc:00:00:01']['hostname'], 'phone')
        self.assertTrue(cl['aa:bb:cc:00:00:01']['online'])
        self.assertEqual(cl['aa:bb:cc:00:00:02']['name'], 'scope-1')
        self.assertEqual(cl['aa:bb:cc:00:00:02']['reserved'], '10.10.10.57')
        self.assertFalse(cl['aa:bb:cc:00:00:03']['online'])                     # lease only, not associated
        self.assertEqual(cl['aa:bb:cc:00:00:03']['hostname'], '')
        self.assertGreater(cl['aa:bb:cc:00:00:03']['expires_in'], 0)


class Map(Base):
    def test_map(self):
        self.start_ap()
        m = netap.map_data('192.168.1.10')
        links = {l['name']: l for l in m['links']}
        self.assertNotIn('lo', links)
        self.assertEqual(links['wlan0']['mode'], 'ap')
        self.assertEqual(links['can0']['kind'], 'can')
        self.assertFalse(links['usb0']['managed'])
        self.assertEqual(m['routes'][0]['dev'], 'end0')
        self.assertTrue(m['ap']['active'])
        self.assertEqual(len(m['ap']['clients']), 3)
        self.assertEqual(m['client_device'], 'end0')


class Routes(Base):
    def test_api(self):
        c = client(logged_in=True)
        d = c.get('/api/netcfg/ap').get_json()
        self.assertEqual(d['wifi_devices'][0]['device'], 'wlan0')
        self.assertFalse(d['settings']['configured'])
        r = c.post('/api/netcfg/ap', json={'settings': dict(AP, address='nope')})
        self.assertEqual(r.status_code, 400)
        r = c.post('/api/netcfg/ap/mode', json={'mode': 'ap', 'ifname': 'wlan0', 'settings': AP, 'password': 'bench-pass-1'})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertIn('left', r.get_json())
        self.assertEqual(c.post('/api/netcfg/ap/restart', json={}).status_code, 409)   # previous change still pending
        self.assertEqual(c.post('/api/netcfg/confirm', json={}).status_code, 200)
        r = c.post('/api/netcfg/dhcp/reservations', json={'reservations': [{'mac': 'aa:bb:cc:00:00:01', 'ip': '10.10.10.40'}]})
        self.assertEqual(r.get_json()['reservations'][0]['ip'], '10.10.10.40')
        self.assertEqual(len(c.get('/api/netcfg/ap/clients').get_json()['clients']), 3)
        self.assertTrue(c.get('/api/netcfg/map').get_json()['ap']['active'])
        s = c.get('/api/netcfg/ap').get_json()['settings']
        self.assertNotIn('psk', s)
        self.assertNotIn('bench-pass', str(c.get('/api/netcfg/ap').get_json()))


if __name__ == '__main__':
    unittest.main()
