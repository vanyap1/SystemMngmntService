"""Access model (CLAUDE.md "Access model"): what anonymous and logged-in users may reach."""
import unittest

from tests.support import client, config

PROTECTED_GET = ['/api/sysinfo', '/api/backups', '/api/backups/job', '/api/tree', '/api/macros', '/api/video_devices',
                 '/api/browse', '/api/devices/gpio', '/api/devices/list', '/api/udev/rules',
                 '/api/net/interfaces', '/api/tests/scripts', '/api/logs', '/api/logs/export.csv',
                 '/api/help/tree', '/api/help/search?q=x', '/api/help/assets?kind=img',
                 '/api/help/diagrams', '/api/git/repos', '/api/git/status', '/api/git/summary', '/api/git/credentials',
                 '/api/git/tree_status', '/api/update/status', '/api/update/job', '/api/i2c/buses', '/api/pyrun/poll',
                 '/api/sysclone/info', '/api/sysclone/job', '/api/sysclone/roots', '/api/modbus/info', '/api/modbus/sessions', '/api/tty/info', '/api/tty/sessions',
                 '/api/display/status', '/api/display/scripts', '/api/display/backgrounds',
                 '/api/uiscreens', '/api/uiscreens/example_dashboard', '/api/video/sources']
PROTECTED_GET_NOCHECK = ['/api/netcfg', '/api/netcfg/pending', '/api/netcfg/wifi', '/api/netcfg/connection?uuid=x']
PROTECTED_POST = ['/api/exec', '/api/backups/deploy', '/api/backups/delete', '/api/backups/create', '/api/backups/cancel', '/api/backups/preview', '/api/backups/tree', '/api/settings',
                  '/api/power/reboot', '/api/file', '/api/udev/action', '/api/net/can/send', '/api/tests/start',
                  '/api/help/doc', '/api/help/create', '/api/help/rename', '/api/help/delete', '/api/help/upload',
                  '/api/help/asset_delete', '/api/help/diagram/create', '/api/help/diagram/save',
                  '/api/help/diagram/rename', '/api/help/diagram/delete', '/api/git/commit', '/api/git/push',
                  '/api/git/pull', '/api/git/fetch', '/api/git/branch', '/api/git/checkout', '/api/git/discard',
                  '/api/git/reset', '/api/git/fix', '/api/git/identity', '/api/git/credentials', '/api/git/clone',
                  '/api/git/init', '/api/update/apply', '/api/update/restart', '/api/update/plan', '/api/update/force', '/api/update/job', '/api/display/settings', '/api/display/restart', '/api/uiscreens/x', '/api/uiscreens/x/delete', '/api/uiscreens/x/show', '/api/video/sources', '/api/video/sources/x/test',
                  '/api/i2c/scan', '/api/i2c/read', '/api/i2c/write', '/api/i2c/label',
                  '/api/pyrun/start', '/api/pyrun/cmd', '/api/pyrun/input', '/api/pyrun/stop', '/api/pyrun/eval',
                  '/api/pyrun/vars', '/api/pyrun/breaks', '/api/term/open', '/api/term/input', '/api/term/resize',
                  '/api/term/close', '/api/sysclone/clone', '/api/sysclone/image', '/api/sysclone/stop',
                  '/api/sysclone/write', '/api/modbus/request', '/api/modbus/scan', '/api/modbus/profiles',
                  '/api/modbus/session/save', '/api/modbus/session/delete', '/api/tty/open', '/api/tty/send',
                  '/api/tty/lines', '/api/tty/close', '/api/tty/profiles', '/api/tty/oneshot', '/api/tty/session/save',
                  '/api/tty/session/delete',
                  '/api/netcfg/connection', '/api/netcfg/activate', '/api/netcfg/deactivate', '/api/netcfg/delete',
                  '/api/netcfg/radio', '/api/netcfg/join', '/api/netcfg/hotspot', '/api/netcfg/confirm', '/api/netcfg/revert',
                  '/api/smb/mount', '/api/smb/umount', '/api/smb/forget', '/api/smb/mkdir']
PROTECTED_PAGES = ['/editor', '/ui', '/settings', '/tests', '/logs', '/backups/download/x.tar.gz', '/help',
                   '/help/file/img/x.png', '/help?diagram=x']


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
                             ('Code Editor', False), ('href="/help"', False), ('power-dropdown', False), ('video-dev-select', False),
                             ('sysinfo.js', False), ('id="mon-float"', False), ('MonitorFloat.toggle', False),
                             ('devices.js', False), ('href="/editor"', False), ('href="/tests"', False),
                             ('upd-wrap', False), ('updates.js', False), ('href="/settings"', False)]:
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
        for url in PROTECTED_GET + PROTECTED_GET_NOCHECK:
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
        for needle in ['Archives', 'System Monitor', 'svc-select', 'href="/editor"', 'href="/settings"', 'href="/help"',
                       'href="/tests"', 'Logout', "svcAction('stop')", 'power-dropdown', 'Devices.open', 'id="upd-wrap"']:
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


class PublicAccess(unittest.TestCase):
    """Settings → Access → Without login: config.public = {home, backups, docs}."""
    TESTS_OPEN = ['/tests', '/logs', '/api/tests/scripts', '/api/tests/status', '/api/tests/logs', '/api/tests/stats',
                  '/api/logs', '/api/logs/export.csv']
    DOCS_OPEN = ['/help', '/api/help/tree', '/api/help/search?q=x']
    BACKUPS_OPEN = ['/api/backups', '/api/backups/job']
    STILL_CLOSED_GET = ['/api/help/assets?kind=img', '/api/help/diagrams', '/api/tree', '/api/git/status', '/settings', '/editor']
    STILL_CLOSED_POST = ['/api/tests/logs/delete', '/api/help/doc', '/api/help/create', '/api/help/diagram/save',
                         '/api/backups/create', '/api/backups/deploy', '/api/backups/delete', '/api/backups/cancel',
                         '/api/settings', '/api/exec']

    def setUp(self):
        self.saved = config.CFG.get('public')
        self.c = client()

    def tearDown(self):
        config.CFG['public'] = self.saved

    def set(self, **kw):
        config.CFG['public'] = dict({'home': 'dashboard', 'backups': False, 'docs': False}, **kw)

    def test_default_everything_closed(self):
        self.set()
        for url in self.TESTS_OPEN + self.DOCS_OPEN + self.BACKUPS_OPEN:
            with self.subTest(url=url):
                self.assertIn(self.c.get(url).status_code, (302, 401))
        self.assertEqual(self.c.post('/api/tests/start', json={}).status_code, 401)

    def test_test_machine(self):
        self.set(home='tests')
        r = self.c.get('/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers['Location'].endswith('/tests'))
        self.assertEqual(self.c.get('/main').status_code, 200)              # the info panel stays reachable
        for url in self.TESTS_OPEN:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 200)
        for url in ('/api/tests/start', '/api/tests/stop', '/api/tests/answer'):
            with self.subTest(url=url):
                self.assertNotEqual(self.c.post(url, json={}).status_code, 401)
        html = self.c.get('/tests').get_data(as_text=True)
        self.assertNotIn('Tests.clearLogs()', html)
        self.assertIn('href="/main"', html)
        self.assertIn('href="/logs"', html)
        self.assertEqual(client(logged_in=True).get('/').status_code, 200)     # logged in: "/" is the info panel
        self.check_closed()

    def test_backups_read_only(self):
        self.set(backups=True)
        for url in self.BACKUPS_OPEN:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 200)
        self.assertEqual(self.c.get('/backups/download/none.tar.gz').status_code, 302)   # allowed, file not found
        html = self.c.get('/').get_data(as_text=True)
        self.assertIn('id="arc-card"', html)
        self.assertNotIn('Create archive', html)
        self.assertNotIn('dep-overlay', html)
        self.check_closed()

    def test_docs_read_only(self):
        self.set(docs=True)
        for url in self.DOCS_OPEN:
            with self.subTest(url=url):
                self.assertEqual(self.c.get(url).status_code, 200)
        html = self.c.get('/help').get_data(as_text=True)
        for needle in ('Help.openNew()', 'Help.edit()', 'Help.remove()', 'git.js', "Help.openAssets('img')"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, html)
        self.assertIn('href="/help"', self.c.get('/').get_data(as_text=True))
        self.check_closed()

    def check_closed(self):
        for url in self.STILL_CLOSED_GET:
            with self.subTest(url=url):
                self.assertIn(self.c.get(url).status_code, (302, 401))
        for url in self.STILL_CLOSED_POST:
            with self.subTest(url=url):
                self.assertEqual(self.c.post(url, json={}).status_code, 401)

    def test_settings_saved_and_sanitised(self):
        lc = client(logged_in=True)
        self.assertEqual(lc.post('/api/settings', json={'public': {'home': 'evil', 'docs': 1}}).status_code, 200)
        self.assertEqual(config.public_access(), {'home': 'dashboard', 'backups': False, 'docs': True})


class AuthDisabled(unittest.TestCase):
    def test_everyone_is_logged_in(self):
        config.CFG['auth']['enabled'] = False
        try:
            self.assertEqual(client().get('/api/backups').status_code, 200)
        finally:
            config.CFG['auth']['enabled'] = True


if __name__ == '__main__':
    unittest.main()
