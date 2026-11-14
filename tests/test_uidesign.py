"""UI designer (core/ui_screens.py, routes/uidesign.py, UI/screen_runner.py): screen validation, store, API, the
display integration (screens/<name>.json run by screen_runner.py), editor colours = device colours, GPU detection.
A temporary project folder holds UI/ — the real screens and the real display are never touched."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from tests.support import TMP, client, config  # noqa: F401  (support first)
from core import display_ui, ui_screens

def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


REPO_UI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'UI')


class Screens(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(self.base, 'UI', 'images'))
        shutil.copy(os.path.join(REPO_UI, 'screen_runner.py'), os.path.join(self.base, 'UI'))
        with open(os.path.join(self.base, 'UI', 'images', 'logo.png'), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n')
        self.p = mock.patch.object(config, 'BASE_DIR', self.base)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        config.CFG.pop('display', None)
        shutil.rmtree(self.base, ignore_errors=True)

    def test_check_cleans_and_clamps(self):
        d = ui_screens.check({'width': 99999, 'height': 10, 'bg': 'red', 'interval': 0, 'widgets': [
            {'type': 'label', 'id': 'a', 'x': 10, 'y': 20, 'text': 'x' * 999, 'size': 9999, 'color': 'nope', 'evil': 1},
            {'type': 'script'},                                              # unknown type: dropped
            {'type': 'value', 'id': 'a', 'path': 'a;rm -rf', 'fmt': 'bad', 'source': 'shell'},   # duplicate id renamed
            {'type': 'image', 'file': '../../etc/passwd.png'}]})
        self.assertEqual((d['width'], d['height'], d['bg'], d['interval']), (7680, 120, '', 0.5))
        lab, val, img = d['widgets']
        self.assertEqual((len(lab['text']), lab['size'], lab['color']), (300, 400, 'text'))
        self.assertNotIn('evil', lab)
        self.assertNotEqual(val['id'], 'a')
        self.assertEqual((val['path'], val['fmt'], val['source']), ('current.cpu.pct', 'int', 'monitor'))
        self.assertEqual(img['file'], '')

    def test_camera_widget(self):
        d = ui_screens.check({'widgets': [{'type': 'camera', 'device': '/dev/video4', 'resolution': '1280x720', 'fps': 500,
                                           'border_w': 5, 'mirror': 1},
                                          {'type': 'camera', 'device': '/etc/passwd', 'resolution': '1280x720; rm'}]})
        good, bad = d['widgets']
        self.assertEqual((good['device'], good['resolution'], good['fps'], good['mirror']), ('/dev/video4', '1280x720', 60, True))
        self.assertEqual((bad['device'], bad['resolution']), ('/dev/video0', '640x480'))
        src = _read(os.path.join(REPO_UI, 'screen_runner.py'))
        self.assertIn("if t == 'camera':", src)
        self.assertIn('w.stop(wait=', src)                    # the device is released before the process ends

    def test_button_actions_validated(self):
        for bad in ({'action': 'post', 'target': 'http://evil/'}, {'action': 'screen', 'target': '../x'},
                    {'action': 'post', 'target': '/api/x', 'body': '{not json'}):
            with self.assertRaises(ui_screens.ScreenError, msg=bad):
                ui_screens.check({'widgets': [dict({'type': 'button'}, **bad)]})

    def test_store_api_and_trash(self):
        c = client(True)
        doc = {'title': 'Main', 'widgets': [{'type': 'value', 'source': 'tests', 'path': 'run.state', 'fmt': 'raw'},
                                            {'type': 'image', 'file': 'logo.png'}]}
        r = c.post('/api/uiscreens/main', json=doc)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(c.post('/api/uiscreens/bad name', json=doc).status_code, 400)
        d = c.get('/api/uiscreens').get_json()
        self.assertEqual([s['name'] for s in d['screens']], ['main'])
        self.assertEqual(d['images'], ['logo.png'])
        self.assertEqual([k for k, _ in d['meta']['types']['value']][:3], ['source', 'path', 'fmt'])   # order kept
        self.assertEqual(c.get('/api/uiscreens/main').get_json()['screen']['widgets'][0]['path'], 'run.state')
        r = c.get('/api/uiscreens/image/logo.png')
        self.assertEqual(r.status_code, 200)
        r.close()
        self.assertEqual(c.get('/api/uiscreens/image/..%2Fx.png').status_code, 404)
        self.assertEqual(c.post('/api/uiscreens/main/delete').status_code, 200)
        self.assertEqual(os.listdir(os.path.join(self.base, 'UI', 'screens'))[0], '.trash')
        self.assertEqual(c.get('/api/uiscreens/main').status_code, 404)

    def test_show_on_device_and_runner_command(self):
        c = client(True)
        c.post('/api/uiscreens/dash', json={'widgets': []})
        with mock.patch.object(display_ui.supervisor, 'kick'):
            r = c.post('/api/uiscreens/dash/show')
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(config.CFG['display']['script'], 'screens/dash.json')
        self.assertTrue(config.CFG['display']['enabled'])
        self.assertIn('screens/dash.json', [s['name'] for s in display_ui.scripts()])
        argv, env = display_ui.command('screens/dash.json')
        self.assertTrue(argv[-1].endswith('UI/screen_runner.py'))
        self.assertEqual(env, {'SMMS_SCREEN': 'dash'})
        self.assertEqual(c.post('/api/uiscreens/nope/show').status_code, 404)
        with self.assertRaises(display_ui.DisplayError):
            display_ui.check({'script': 'screens/../x.json'})


class Parity(unittest.TestCase):
    def test_editor_colours_are_the_device_colours(self):
        sys.path.insert(0, REPO_UI)
        try:
            import smms_ui
            for k, hexv in ui_screens.THEME_HEX.items():
                dev = smms_ui.hexcolor(smms_ui.THEME[k])
                for i in (0, 2, 4):
                    self.assertLessEqual(abs(int(hexv[1 + i:3 + i], 16) - int(dev[i:i + 2], 16)), 2, k)
        finally:
            sys.path.remove(REPO_UI)

    def test_runner_and_editor_know_every_format(self):
        src = _read(os.path.join(REPO_UI, 'screen_runner.py'))
        js = _read(os.path.join(os.path.dirname(REPO_UI), 'static', 'js', 'uidesign.js'))
        for kind in ui_screens.FMTS[1:]:
            self.assertIn(f"'{kind}'", src)
            self.assertIn(f"'{kind}'", js)


class Gpu(unittest.TestCase):
    def _tree(self, driver):
        root = tempfile.mkdtemp(dir=TMP)
        drv = os.path.join(root, 'drivers', driver)
        os.makedirs(drv)
        dev = os.path.join(root, 'gpu')
        os.makedirs(dev)
        os.symlink(drv, os.path.join(dev, 'driver'))
        os.makedirs(os.path.join(root, 'drm', 'renderD128'))
        os.symlink(dev, os.path.join(root, 'drm', 'renderD128', 'device'))
        con = os.path.join(root, 'drm', 'card0-HDMI-A-1')
        os.makedirs(con)
        for name, text in (('status', 'connected\n'), ('modes', '1280x720\n')):
            with open(os.path.join(con, name), 'w') as f:
                f.write(text)
        return os.path.join(root, 'drm')

    def test_detection(self):
        g = display_ui.gpu_info(None, self._tree('lima'))
        self.assertTrue(g['hw'])
        self.assertEqual(g['nodes'][0]['driver'], 'lima')
        self.assertEqual(g['outputs'][0]['mode'], '1280x720')
        self.assertFalse(display_ui.gpu_info(None, self._tree('vgem'))['hw'])          # no GPU behind the node
        self.assertFalse(display_ui.gpu_info('llvmpipe (LLVM 15.0.6, 128 bits)', self._tree('lima'))['hw'])
        self.assertTrue(display_ui.gpu_info('llvmpipe', self._tree('lima'))['software'])
        empty = tempfile.mkdtemp(dir=TMP)
        self.assertFalse(display_ui.gpu_info(None, empty)['hw'])

    def test_renderer_from_the_log(self):
        m = display_ui._RENDERER.search("[INFO   ] [GL          ] OpenGL renderer <b'Mali-G52 r1 (Panfrost)'>")
        self.assertEqual(m.group(1), 'Mali-G52 r1 (Panfrost)')


if __name__ == '__main__':
    unittest.main()
