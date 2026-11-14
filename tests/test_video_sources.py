"""Network video sources (core/video_sources.py, routes/video.py, Settings → Video): credentials split from the URL,
write-only password, scrubbing, net:<name> in the device list / feed / camera widget / display environment.
No camera is contacted (ffprobe / ffmpeg are never run here)."""
import json
import unittest
from unittest import mock

from tests.support import client, config  # noqa: F401  (support first)
from core import display_ui, ui_screens, video_sources

URL = 'rtsp://admin:p%40ss:w0rd@192.168.1.108:554/cam/realmonitor?channel=1&subtype=1'


class Sources(unittest.TestCase):
    def tearDown(self):
        config.CFG['video_sources'] = []

    def test_save_splits_the_login_and_hides_the_password(self):
        pub = video_sources.save([{'name': 'gate', 'url': URL}])
        self.assertEqual(pub, [{'name': 'gate', 'url': 'rtsp://192.168.1.108:554/cam/realmonitor?channel=1&subtype=1',
                                'username': 'admin', 'password_set': True, 'transport': 'tcp'}])
        stored = config.CFG['video_sources'][0]
        self.assertEqual(stored['password'], 'p@ss:w0rd')
        self.assertEqual(video_sources.full_url(stored),
                         'rtsp://admin:p%40ss%3Aw0rd@192.168.1.108:554/cam/realmonitor?channel=1&subtype=1')
        video_sources.save([{'name': 'gate', 'url': pub[0]['url'], 'username': 'admin', 'password': ''}])   # kept
        self.assertEqual(config.CFG['video_sources'][0]['password'], 'p@ss:w0rd')
        self.assertNotIn('p@ss', json.dumps(video_sources.public()))
        msg = video_sources.scrub(f'Connection to {video_sources.full_url(stored)} failed: p@ss:w0rd')
        self.assertNotIn('p@ss', msg)
        self.assertNotIn('w0rd', msg)

    def test_validation(self):
        for bad in ([{'name': 'a b', 'url': URL}], [{'name': 'x', 'url': 'file:///etc/passwd'}],
                    [{'name': 'x', 'url': URL}, {'name': 'x', 'url': URL}], 'nope'):
            with self.assertRaises(video_sources.SourceError, msg=bad):
                video_sources.save(bad)

    def test_api_devices_feed_and_access(self):
        c = client(True)
        r = c.post('/api/video/sources', json={'sources': [{'name': 'gate', 'url': URL}]})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('w0rd', r.get_data(as_text=True))
        self.assertNotIn('w0rd', c.get('/api/video/sources').get_data(as_text=True))
        devs = c.get('/api/video_devices').get_json()['devices']
        self.assertIn('net:gate', [d['path'] for d in devs])
        self.assertNotIn('w0rd', json.dumps(devs))
        self.assertEqual(c.get('/api/video_resolutions?device=net:gate').get_json()['resolutions'][0], 'source')
        self.assertEqual(c.get('/api/video_feed?device=net:nope').status_code, 404)
        self.assertEqual(client().get('/api/video/sources').status_code, 401)
        with mock.patch('subprocess.run') as run:
            run.return_value = mock.Mock(returncode=0, stdout='{"streams": [{"codec_name": "h264", "width": 704, "height": 576}]}', stderr='')
            self.assertEqual(c.post('/api/video/sources/gate/test').get_json(), {'ok': True, 'video': 'h264 704x576'})
            self.assertIn('-rtsp_transport', run.call_args[0][0])

    def test_default_camera_of_the_video_window(self):
        c = client(True)
        self.assertEqual(c.get('/api/video/default').get_json()['device'], '')
        self.assertEqual(c.post('/api/video/default', json={'device': 'net:gate', 'resolution': 'source'}).status_code, 200)
        self.assertEqual(c.get('/api/video/default').get_json(), {'device': 'net:gate', 'resolution': 'source'})
        for bad in ({'device': '/etc/passwd'}, {'device': '/dev/video1', 'resolution': '1x1; rm'}):
            self.assertEqual(c.post('/api/video/default', json=bad).status_code, 400, bad)
        config.CFG['video'] = {}

    def test_camera_widget_and_display_environment(self):
        video_sources.save([{'name': 'gate', 'url': URL, 'transport': 'udp'}])
        w = ui_screens.check({'widgets': [{'type': 'camera', 'device': 'net:gate'}]})['widgets'][0]
        self.assertEqual(w['device'], 'net:gate')
        env = display_ui.child_env(dict(display_ui.DEFAULTS), 'kmsdrm', display_ui.run_user(), 't')
        srcs = json.loads(env['SMMS_VIDEO_SOURCES'])
        self.assertEqual(srcs['gate']['transport'], 'udp')
        self.assertIn('admin:p%40ss', srcs['gate']['url'])


if __name__ == '__main__':
    unittest.main()
