"""Access model (CLAUDE.md "Access model"): what anonymous and logged-in users may reach."""
import unittest

from tests.support import client, config

PROTECTED_GET = ['/api/sysinfo', '/api/backups', '/api/tree', '/api/macros', '/api/video_devices',
                 '/api/browse', '/api/devices/gpio', '/api/devices/list', '/api/udev/rules',
                 '/api/net/interfaces', '/api/tests/scripts', '/api/logs', '/api/logs/export.csv']
PROTECTED_POST = ['/api/exec', '/api/backups/deploy', '/api/backups/delete', '/backups/create', '/api/settings',
                  '/api/power/reboot', '/api/file', '/api/udev/action', '/api/net/can/send', '/api/tests/start']
PROTECTED_PAGES = ['/editor', '/settings', '/tests', '/logs', '/backups/download/x.tar.gz']


class Anonymous(unittest.TestCase):
    def setUp(self):
        self.c = client()

    def test_index_shows_target_service_and_monitor_only(self):
        r = self.c.get('/')
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        for needle, want in [('Service Control', True), ('System Monitor', True), ('id="mon-card"', True),
                             ('monitor.js', True), (config.service_name(), True), ('> Login', True),
                             ("svcAction('restart')", True), ("svcAction('stop')", False),
                             ('svc-select', False), ('Services.openModal', False), ('Archives', False),
                             ('Code Editor', False), ('power-dropdown', False), ('video-dev-select', False),
                             ('sysinfo.js', False), ('id="mon-float"', False), ('MonitorFloat.toggle', False),
                             ('devices.js', False)]:
            with self.subTest(needle=needle):
                self.assertEqual(needle in html, want)

    def test_public_api(self):
        for url in ['/api/services', '/api/status', '/api/monitor']:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 200)

    def test_services_list_is_target_only(self):
        data = self.c.get('/api/services').get_json()
        self.assertTrue({s['name'] for s in data['services']} <= {config.service_name()})

    def test_restart_ignores_foreign_name(self):
        self.assertEqual(self.c.post('/api/service/restart?name=ssh.service').status_code, 200)

    def test_actions_outside_public_list_need_login(self):
        self.assertEqual(self.c.post('/api/service/stop').status_code, 401)
        self.assertEqual(self.c.get('/api/service/restart').status_code, 405)

    def test_protected_api_returns_401(self):
        for url in PROTECTED_GET:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 401)
        for url in PROTECTED_POST:
            with self.subTest(url=url):
                self.assertEqual(self.c.post(url, json={}).status_code, 401)

    def test_protected_pages_redirect_to_login(self):
        for url in PROTECTED_PAGES:
            with self.subTest(url=url):
                r = self.c.get(url)
                self.assertEqual(r.status_code, 302)
                self.assertIn('/login', r.headers['Location'])

    def test_login(self):
        self.assertEqual(self.c.get('/login').status_code, 200)
        self.assertEqual(self.c.post('/login', data={'login': 'x', 'password': 'y'}).status_code, 200)

    def test_open_redirect_blocked(self):
        r = self.c.post('/login?next=//evil.com', data={'login': 'test', 'password': 'test'})
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('evil.com', r.headers['Location'])


class LoggedIn(unittest.TestCase):
    def setUp(self):
        self.c = client(logged_in=True)

    def test_index_has_everything(self):
        html = self.c.get('/').get_data(as_text=True)
        for needle in ['Archives', 'System Monitor', 'svc-select', 'Code Editor', 'Settings', 'Logout',
                       "svcAction('stop')", 'power-dropdown', 'Devices.open']:
            with self.subTest(needle=needle):
                self.assertIn(needle, html)
        self.assertNotIn('id="mon-float"', html)      # the floating monitor is for other pages

    def test_other_pages_have_floating_monitor(self):
        for url in ['/editor', '/settings', '/tests', '/logs']:
            with self.subTest(url=url):
                r = self.c.get(url)
                self.assertEqual(r.status_code, 200)
                self.assertIn('id="mon-float"', r.get_data(as_text=True))

    def test_protected_api_ok(self):
        for url in PROTECTED_GET + ['/api/monitor']:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 200)

    def test_any_service_allowed(self):
        self.assertEqual(self.c.post('/api/service/stop?name=bad').status_code, 400)   # validated, not 401

    def test_file_outside_target_dir(self):
        self.assertEqual(self.c.get('/api/file?path=/etc/passwd').status_code, 403)

    def test_logout(self):
        self.assertEqual(self.c.get('/logout').status_code, 302)
        self.assertEqual(self.c.get('/api/tree').status_code, 401)


class AuthDisabled(unittest.TestCase):
    def test_everyone_is_logged_in(self):
        config.CFG['auth']['enabled'] = False
        try:
            self.assertEqual(client().get('/api/backups').status_code, 200)
        finally:
            config.CFG['auth']['enabled'] = True


if __name__ == '__main__':
    unittest.main()
