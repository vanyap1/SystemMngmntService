"""config.json store: legacy migration, per-host sections, save and reset (on a temporary file)."""
import json
import os
import unittest

from tests.support import TMP, config


class ConfigStore(unittest.TestCase):
    def setUp(self):
        self._saved = (config.CONFIG_PATH, config.HOSTNAME, dict(config.CFG), dict(config._FILE))
        config.CONFIG_PATH = os.path.join(TMP, 'cfg_test.json')
        config.HOSTNAME = 'box1'

    def tearDown(self):
        config.CONFIG_PATH, config.HOSTNAME, cfg, raw = self._saved
        config.CFG.clear(); config.CFG.update(cfg)
        config._FILE.clear(); config._FILE.update(raw)

    def _write(self, data):
        with open(config.CONFIG_PATH, 'w') as f:
            json.dump(data, f)

    def _raw(self):
        with open(config.CONFIG_PATH) as f:
            return json.load(f)

    def test_legacy_flat_config_is_migrated(self):
        self._write({'target_dir': '/srv/app', 'device_name': 'Box', 'port': 81})
        config.load()
        raw = self._raw()
        self.assertEqual(sorted(raw), ['default', 'hosts'])
        self.assertEqual(raw['hosts']['box1']['device_name'], 'Box')
        self.assertEqual(raw['default']['device_name'], '')
        self.assertEqual(config.target_dir(), '/srv/app')

    def test_base_config_layers_under_the_local_one(self):
        base = os.path.join(TMP, 'cfg_base.json')
        saved = config.BASE_CONFIG_PATH
        config.BASE_CONFIG_PATH = base
        try:
            with open(base, 'w') as f:
                json.dump({'_comment': 'x', 'default': {'device_name': 'Base', 'port': 8080, 'app_title': 'Shared'}}, f)
            self._write({'default': {'port': 81}, 'hosts': {'box1': {'device_name': 'Box'}}})
            config.load()
            self.assertEqual((config.get('app_title'), config.get('port'), config.get('device_name')), ('Shared', 81, 'Box'))
            os.remove(config.CONFIG_PATH)                    # a fresh clone: no local config.json yet
            config.load()
            self.assertEqual((config.get('port'), config.get('device_name')), (8080, 'Base'))
            config.save_key('i2c_labels', {})                # the panel writes only the local file
            with open(base) as f:
                self.assertNotIn('hosts', json.load(f))
            self.assertIn('box1', self._raw()['hosts'])
        finally:
            config.BASE_CONFIG_PATH = saved

    def test_repository_tracks_only_the_base_config(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, '.gitignore')) as f:
            self.assertIn('config.json', [ln.strip() for ln in f])
        with open(os.path.join(root, 'config.base.json')) as f:
            d = json.load(f)
        self.assertEqual(sorted(k for k in d if not k.startswith('_')), ['default'])

    def test_unknown_host_runs_on_defaults(self):
        self._write({'default': {'target_dir': '/opt/x'}, 'hosts': {'other': {'target_dir': '/nope'}}})
        config.load()
        self.assertIsNone(config.host_section())
        self.assertEqual(config.target_dir(), '/opt/x')
        self.assertEqual(config.get('port'), config.BUILTIN_DEFAULTS['port'])

    def test_deep_merge_of_auth(self):
        self._write({'default': {'auth': {'password': 'p'}}, 'hosts': {'box1': {'auth': {'username': 'u'}}}})
        config.load()
        self.assertEqual(config.auth(), {'enabled': True, 'username': 'u', 'password': 'p'})

    def test_update_writes_only_this_host(self):
        self._write({'default': {'target_dir': '/opt/x'}, 'hosts': {}})
        config.load()
        config.update({'device_name': 'Box2', 'port': '8080', 'public_service_actions': ['stop', 'rm -rf']})
        raw = self._raw()
        self.assertEqual(raw['hosts']['box1']['device_name'], 'Box2')
        self.assertEqual(raw['hosts']['box1']['port'], 8080)
        self.assertEqual(raw['hosts']['box1']['public_service_actions'], ['stop'])
        self.assertEqual(raw['default'], {'target_dir': '/opt/x'})
        config.reset_host()
        self.assertNotIn('box1', self._raw()['hosts'])
        self.assertEqual(config.get('device_name'), '')


if __name__ == '__main__':
    unittest.main()
