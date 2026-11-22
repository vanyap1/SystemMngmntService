"""Settings → General → System host name (core/hostname.py, config.rename_host). The real hostname, /etc/hosts and
hostnamectl are never touched: _run and socket.gethostname are mocked, paths point into a temp dir."""
import copy
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests.support import client
from core import config, hostname


class Hostname(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='smms-hn-')
        self.hosts = os.path.join(self.tmp, 'hosts')
        with open(self.hosts, 'w') as f:
            f.write('127.0.0.1   localhost\n127.0.1.1   oldbox oldbox.lan\n::1 localhost ip6-localhost\n')
        self.name = 'oldbox'
        self.cmds = []
        self.saved = (config.HOSTNAME, copy.deepcopy(config._FILE), copy.deepcopy(config.CFG))
        config.HOSTNAME = 'oldbox'
        config._FILE.setdefault('hosts', {})['oldbox'] = {'device_name': 'Bench'}
        config._FILE['hosts'].pop('newbox', None)

        def run(argv):
            self.cmds.append(argv)
            if argv[:2] == ['hostnamectl', 'set-hostname']:
                self.name = argv[2]
        self.patches = [mock.patch.object(hostname, 'HOSTS_PATH', self.hosts),
                        mock.patch.object(hostname, '_run', run),
                        mock.patch.object(hostname.shutil, 'which', lambda c: '/usr/bin/' + c),
                        mock.patch.object(hostname.socket, 'gethostname', lambda: self.name),
                        mock.patch.object(hostname.subprocess, 'run',
                                          lambda *a, **k: mock.Mock(stdout='', returncode=0))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        config.HOSTNAME = self.saved[0]
        config._FILE.clear()
        config._FILE.update(self.saved[1])
        config._write()
        config.CFG.clear()
        config.CFG.update(self.saved[2])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rename(self):
        r = hostname.set_hostname('newbox')
        self.assertEqual(self.cmds, [['hostnamectl', 'set-hostname', 'newbox']])
        self.assertTrue(r['changed'] and r['moved_section'])
        with open(self.hosts) as f:
            text = f.read()
        self.assertIn('127.0.1.1   newbox newbox.lan\n', text)
        self.assertIn('127.0.0.1   localhost\n', text)
        self.assertEqual(config.HOSTNAME, 'newbox')
        self.assertNotIn('oldbox', config._FILE['hosts'])
        self.assertEqual(config.host_section(), {'device_name': 'Bench'})

    def test_missing_hosts_line_is_added(self):
        with open(self.hosts, 'w') as f:
            f.write('127.0.0.1 localhost\n')
        hostname.set_hostname('newbox')
        with open(self.hosts) as f:
            self.assertEqual(f.read(), '127.0.0.1 localhost\n127.0.1.1\tnewbox\n')

    def test_validation(self):
        for bad in ('', '-x', 'x-', 'a b', 'x' * 64, '123', 'bad;reboot', 'дім', None, 5):
            with self.subTest(bad=bad), self.assertRaises(hostname.HostnameError):
                hostname.set_hostname(bad)
        self.assertEqual(self.cmds, [])
        self.assertEqual(hostname.check('Bench-3'), 'Bench-3')

    def test_api(self):
        c = client(logged_in=True)
        self.assertEqual(c.get('/api/system/hostname').get_json()['hostname'], 'oldbox')
        self.assertEqual(c.post('/api/system/hostname', json={'hostname': 'a b'}).status_code, 400)
        r = c.post('/api/system/hostname', json={'hostname': 'newbox'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['hostname'], 'newbox')


if __name__ == '__main__':
    unittest.main()
