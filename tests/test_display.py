"""Device display (core/display_ui.py, routes/display.py, UI/): settings, scripts, the API token of the display
script, the supervisor (start / replace on the fly / restart after a crash / switch off) with a fake script in a
temporary UI/ folder — Kivy is never started and the real screen is never touched here."""
import os
import py_compile
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests.support import TMP, client, config  # noqa: F401  (support first)
from core import display_ui

FAKE = r'''"""Fake display script: prints its environment, exits on SIGTERM."""
import os, signal, sys, time
signal.signal(signal.SIGTERM, lambda *a: (print('got SIGTERM', flush=True), sys.exit(0)))
print('fake', os.path.basename(__file__), os.environ['SDL_VIDEODRIVER'], os.environ['SMMS_DISPLAY'][:40], flush=True)
if os.path.basename(__file__) == 'crash.py':
    sys.exit(3)
while True:
    time.sleep(0.05)
'''
REPO_UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'UI')


class Settings(unittest.TestCase):
    def tearDown(self):
        config.CFG.pop('display', None)

    def test_defaults_and_validation(self):
        s = display_ui.check({})
        self.assertFalse(s['enabled'])
        self.assertEqual((s['mode'], s['rotation'], s['scale']), ('auto', 0, 0))
        for bad in ({'mode': 'wayland'}, {'rotation': 45}, {'width': -1}, {'cursor': 'x'}, {'x_display': 'host:0'},
                    {'script': '../x.py'}, {'script': 'smms_ui.py'}, {'fps': 0}):
            with self.assertRaises(display_ui.DisplayError, msg=bad):
                display_ui.check(bad)

    def test_scripts_of_the_repository(self):
        with mock.patch.object(config, 'BASE_DIR', os.path.dirname(REPO_UI)):
            names = [s['name'] for s in display_ui.scripts() if s['name'].endswith('.py')]
        self.assertEqual(names, ['demo_chart.py', 'demo_controls.py', 'system_monitor.py', 'test_status.py'])
        for n in names + ['smms_ui.py', 'screen_runner.py']:
            py_compile.compile(os.path.join(REPO_UI, n), doraise=True, cfile=os.path.join(TMP, n + 'c'))

    def test_api_settings_and_unknown_script(self):
        c = client(True)
        r = c.post('/api/display/settings', json={'enabled': True, 'script': 'nope.py'})
        self.assertEqual(r.status_code, 404)
        r = c.post('/api/display/settings', json={'enabled': False, 'script': 'system_monitor.py', 'rotation': 90})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(config.CFG['display']['rotation'], 90)
        self.assertEqual(c.get('/api/display/status').get_json()['state'], 'off')

    def test_backgrounds(self):
        with mock.patch.object(config, 'BASE_DIR', os.path.dirname(REPO_UI)):
            names = [b['name'] for b in display_ui.backgrounds()]
            self.assertIn('wallpaper.jpg', names)
            c = client(True)
            r = c.get('/api/display/background/wallpaper.jpg')
            self.assertEqual((r.status_code, r.mimetype), (200, 'image/jpeg'))
            r.close()
            for bad in ('..%2Fsmms_ui.py', 'nope.jpg', 'x.py'):
                self.assertEqual(c.get('/api/display/background/' + bad).status_code, 404, bad)
            self.assertEqual(client().get('/api/display/background/wallpaper.jpg').status_code, 401)
            r = c.post('/api/display/settings', json={'enabled': False, 'background': 'wallpaper.jpg', 'bg_dim': 30})
            self.assertEqual(r.status_code, 200)
            self.assertEqual((config.CFG['display']['background'], config.CFG['display']['bg_dim']), ('wallpaper.jpg', 30))
            self.assertEqual(c.post('/api/display/settings', json={'background': 'missing.png'}).status_code, 404)
            self.assertEqual(c.post('/api/display/settings', json={'background': '../etc/x.png'}).status_code, 400)
            self.assertEqual(c.post('/api/display/settings', json={'bg_dim': 99}).status_code, 400)

    def test_helper_settings_and_density(self):
        sys.path.insert(0, REPO_UI)
        try:
            import smms_ui
            with mock.patch.dict(os.environ, {'SMMS_DISPLAY': '{"width": 800, "height": 480, "scale": 0}'}):
                self.assertEqual(smms_ui.screen_size(), (800, 480))
                self.assertEqual(smms_ui.density(), 0.75)          # clamped
            with mock.patch.dict(os.environ, {'SMMS_DISPLAY': '{"width": 1920, "height": 1080}'}):
                self.assertEqual(smms_ui.density(), 1.5)
            with mock.patch.dict(os.environ, {'SMMS_DISPLAY': '{"scale": 125}'}):
                self.assertEqual(smms_ui.density(), 1.25)
        finally:
            sys.path.remove(REPO_UI)


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(self.base, 'UI'))
        for name in ('one.py', 'two.py', 'crash.py'):
            with open(os.path.join(self.base, 'UI', name), 'w') as f:
                f.write(FAKE)
        self.patches = [mock.patch.object(config, 'BASE_DIR', self.base),
                        mock.patch.object(display_ui, 'kivy_version', return_value='2.1.0'),
                        mock.patch.object(display_ui, 'x_running', return_value=False)]
        for p in self.patches:
            p.start()
        self.sv = display_ui.Supervisor()
        self.real = display_ui.supervisor
        display_ui.supervisor = self.sv

    def tearDown(self):
        self.sv.stop_all()
        display_ui.supervisor = self.real
        for p in self.patches:
            p.stop()
        config.CFG.pop('display', None)
        shutil.rmtree(self.base, ignore_errors=True)

    def _set(self, **kw):
        config.CFG['display'] = dict(display_ui.DEFAULTS, **kw)

    def _log(self, text, t=5):
        end = time.time() + t
        while time.time() < end:
            if any(text in ln for ln in self.sv.log):
                return True
            time.sleep(0.05)
        self.fail(f'{text!r} not in the log: {list(self.sv.log)}')

    def test_start_replace_switch_off(self):
        self._set(enabled=True, script='one.py')
        self.sv.tick()
        st = self.sv.status()
        self.assertEqual((st['state'], st['script'], st['mode']), ('running', 'one.py', 'kmsdrm'))
        self._log('fake one.py kmsdrm')
        token = self.sv.token
        self.assertTrue(display_ui.check_token(token))
        self._set(enabled=True, script='two.py')             # replaced on the fly
        self.sv.tick()
        self._log('got SIGTERM')
        self.assertEqual(self.sv.status()['script'], 'two.py')
        self.assertFalse(display_ui.check_token(token))       # the old token dies with its process
        self._set(enabled=True, script='two.py', rotation=180)  # any setting change restarts it
        self.sv.tick()
        self.assertEqual(self.sv.status()['restarts'], 2)
        self._set(enabled=False, script='two.py')
        self.sv.tick()
        st = self.sv.status()
        self.assertEqual((st['state'], st['pid']), ('off', None))
        self.assertFalse(display_ui.check_token(token))

    def test_crash_backoff(self):
        self._set(enabled=True, script='crash.py')
        self.sv.tick()
        self.sv.proc.wait(5)
        self.sv.tick()                                         # exit noticed, restart delayed
        st = self.sv.status()
        self.assertEqual(st['last_exit']['code'], 3)
        self.assertEqual(st['state'], 'waiting')
        self.assertGreater(st['next_start_in'], 0)
        self.sv.tick()
        self.assertIsNone(self.sv.proc)                        # not before the delay
        self.sv.kick()                                         # Apply / Restart: at once
        self.sv.tick()
        self.assertIsNotNone(self.sv.proc)

    def test_missing_kivy_or_script(self):
        self._set(enabled=True, script='gone.py')
        self.sv.tick()
        self.assertEqual(self.sv.status()['state'], 'error')
        with mock.patch.object(display_ui, 'kivy_version', return_value=None):
            self._set(enabled=True, script='one.py')
            self.sv.tick()
            self.assertIn('Kivy', self.sv.status()['error'])
        self.assertIsNone(self.sv.proc)

    def test_token_only_from_loopback(self):
        self._set(enabled=True, script='one.py')
        self.sv.tick()
        c = client(False)
        url = '/api/display/status'
        self.assertEqual(c.get(url, headers={'X-SMMS-Token': self.sv.token}).status_code, 200)
        self.assertEqual(c.get(url, headers={'X-SMMS-Token': 'wrong'}).status_code, 401)
        self.assertEqual(c.get(url, headers={'X-SMMS-Token': self.sv.token},
                               environ_base={'REMOTE_ADDR': '192.168.1.50'}).status_code, 401)

    def test_x11_environment(self):
        user = display_ui.run_user()
        env = display_ui.child_env(dict(display_ui.DEFAULTS, x_display=':1'), 'x11', user, 't')
        self.assertEqual((env['DISPLAY'], env['SDL_VIDEODRIVER']), (':1', 'x11'))
        env = display_ui.child_env(dict(display_ui.DEFAULTS), 'kmsdrm', user, 't')
        self.assertEqual(env['SDL_VIDEODRIVER'], 'kmsdrm')
        self.assertNotIn('DISPLAY', env)
        self.assertTrue(env['SMMS_API'].startswith('http://127.0.0.1:'))


if __name__ == '__main__':
    unittest.main()
