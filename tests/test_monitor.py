"""core.monitor: sampler, lease, active interface detection and the /api/monitor payload."""
import time
import unittest
from unittest import mock

from tests.support import client
from core import monitor as mon

ROUTE = ('Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n'
         'wlan0\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\n'
         'eth0\t00000000\t0105A8C0\t0003\t0\t0\t100\t00000000\n'
         'eth0\t0005A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\n')


class ActiveInterface(unittest.TestCase):
    def test_default_route_with_lowest_metric(self):
        real = mon._read
        with mock.patch.object(mon, '_read', lambda p, d='': ROUTE if p == '/proc/net/route' else real(p, d)):
            self.assertEqual(mon._default_iface(), ('eth0', '192.168.5.1'))


class Sampler(unittest.TestCase):
    def test_lease_stops_and_restarts_the_thread(self):
        m = mon.Monitor()
        with mock.patch.object(mon, 'LEASE_SECONDS', 1.5):
            m.snapshot()
            time.sleep(2.5)
            self.assertGreaterEqual(len(m.history), 1)
            time.sleep(1.5)
            self.assertIsNone(m._thread)
            m.snapshot()
            self.assertIsNotNone(m._thread)

    def test_snapshot_payload(self):
        m = mon.Monitor()
        m.snapshot()
        time.sleep(2.3)
        d = m.snapshot()
        self.assertEqual(set(d), {'now', 'interval', 'uptime', 'hostname', 'current', 'blocks', 'history'})
        cur = d['current']
        self.assertTrue(0 <= cur['cpu']['pct'] <= 100)
        self.assertEqual(len(cur['cpu']['cores']), cur['cpu']['count'])
        self.assertTrue(0 < cur['mem']['pct'] < 100)
        self.assertTrue(all(len(h) == 6 for h in d['history']))
        self.assertEqual(m.snapshot(since=d['history'][-1][0])['history'], [])
        self.assertFalse(any(b['name'].startswith(('loop', 'ram')) for b in d['blocks']))


class Api(unittest.TestCase):
    def test_public_and_since(self):
        c = client()
        self.assertEqual(c.get('/api/monitor?since=abc').status_code, 200)
        self.assertEqual(c.get('/api/monitor?since=9999999999').get_json()['history'], [])


if __name__ == '__main__':
    unittest.main()
