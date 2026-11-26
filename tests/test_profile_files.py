"""core/profile_files.py: HW Utils profiles in git (hwProfiles/<kind>.json) with migration from config.json."""
import json
import os
import shutil
import unittest

from tests.support import client, config
from core import profile_files


class ProfileFiles(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(config.profiles_dir(), ignore_errors=True)
        self.saved = {k: config.CFG.get(k) for k in profile_files.KINDS}

    def tearDown(self):
        for k, v in self.saved.items():
            config.CFG[k] = v if v is not None else {}

    def test_migration_from_config(self):
        legacy = {'profiles': [{'name': 'Old', 'tx': []}], 'current': 'Old'}
        config.CFG['can'] = legacy
        self.assertEqual(profile_files.load('can'), legacy)                     # no file yet: config.json
        new = {'profiles': [{'name': 'New', 'tx': []}], 'current': 'New'}
        profile_files.save('can', new)
        path = os.path.join(config.profiles_dir(), 'can.json')
        with open(path, encoding='utf-8') as f:
            self.assertEqual(json.load(f), new)
        self.assertEqual(config.CFG['can'], {})                                 # the section moved out
        self.assertEqual(profile_files.load('can'), new)
        self.assertFalse(os.path.exists(path + '.tmp'))

    def test_broken_file_and_bad_kind(self):
        os.makedirs(config.profiles_dir())
        with open(os.path.join(config.profiles_dir(), 'tty.json'), 'w') as f:
            f.write('{broken')
        self.assertEqual(profile_files.load('tty'), {})
        with self.assertRaises(ValueError):
            profile_files.load('../config')

    def test_routes_write_files(self):
        c = client(logged_in=True)
        self.assertEqual(c.post('/api/tty/profiles', json={'profiles': [{'name': 'A'}], 'current': 'A'}).status_code, 200)
        self.assertEqual(c.post('/api/modbus/profiles', json={'profiles': [{'name': 'P', 'conn': {'transport': 'tcp'},
                                                                            'macros': []}], 'current': 'P'}).status_code, 200)
        self.assertEqual(sorted(os.listdir(config.profiles_dir())), ['modbus.json', 'tty.json'])
        self.assertEqual(c.get('/api/tty/info').get_json()['profiles'][0]['name'], 'A')
        self.assertEqual(c.get('/api/modbus/info').get_json()['profiles'][0]['name'], 'P')


if __name__ == '__main__':
    unittest.main()
