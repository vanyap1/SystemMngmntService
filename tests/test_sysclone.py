"""HW Utils -> Clone / Image: core/sysclone.py, core/smb.py, routes/sysclone.py, tools/clone-system.sh.

Nothing here touches a real disk, mounts a share or needs root: lsblk / the script / mount(2) are replaced by fakes,
the share is a temporary folder.
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from tests.support import client, config  # noqa: F401  (isolates config / credentials)
from core import credentials, smb, sysclone

TREE = [
    {'name': 'mmcblk0', 'path': '/dev/mmcblk0', 'size': 31268536320, 'type': 'disk', 'tran': None, 'model': None, 'rm': False,
     'mountpoints': [None], 'children': [
         {'name': 'mmcblk0p1', 'path': '/dev/mmcblk0p1', 'size': 30000000000, 'type': 'part', 'fstype': 'ext4',
          'label': 'armbi_root', 'mountpoints': ['/var/log.hdd', '/']}]},
    {'name': 'mmcblk0boot0', 'path': '/dev/mmcblk0boot0', 'size': 4194304, 'type': 'disk', 'mountpoints': [None]},
    {'name': 'zram0', 'path': '/dev/zram0', 'size': 2000000000, 'type': 'disk', 'mountpoints': ['[SWAP]']},
    {'name': 'loop3', 'path': '/dev/loop3', 'size': 1000, 'type': 'loop', 'mountpoints': [None]},
    {'name': 'sda', 'path': '/dev/sda', 'size': 16000000000, 'type': 'disk', 'tran': 'usb', 'model': 'Flash Disk ', 'rm': True,
     'mountpoints': [None], 'children': [
         {'name': 'sda1', 'path': '/dev/sda1', 'size': 15999000000, 'type': 'part', 'fstype': 'vfat', 'label': 'DATA',
          'mountpoints': ['/media/usb']}]},
    {'name': 'mmcblk1', 'path': '/dev/mmcblk1', 'size': 8000000000, 'type': 'disk', 'mountpoints': [None]},
]

FAKE_SCRIPT = r'''#!/bin/bash
echo "==> target ${TARGET_DISK:-$IMAGE_FILE} extra=${EXTRA_MB:-} size=${TARGET_SIZE_MB:-} grow=$GROW_ON_BOOT compress=${COMPRESS:-}"
printf '  1,000,000  10%%   5.00MB/s    0:00:30 (xfr#1, to-chk=9/10)\r'
printf '  9,000,000  95%%   5.00MB/s    0:00:01 (xfr#9, to-chk=0/10)\n'
if [[ ${FAIL:-} == yes ]]; then echo "ERROR: boom" >&2; exit 3; fi
if [[ -n ${SLOW:-} ]]; then trap 'echo stopped; exit 143' TERM; sleep 30 & wait; fi
echo "==> Done: system copied to ${TARGET_DISK}1 (UUID=x, 100 MiB)"
'''


class Disks(unittest.TestCase):
    def test_candidates_and_system_disk(self):
        ds = {d['name']: d for d in sysclone.disks(TREE, '/dev/mmcblk0p1')}
        self.assertEqual(sorted(ds), ['mmcblk0', 'mmcblk1', 'sda'])            # no boot0 / zram / loop
        self.assertTrue(ds['mmcblk0']['system'])
        self.assertFalse(ds['sda']['system'])
        self.assertEqual(ds['sda']['mounted'], ['/media/usb'])
        self.assertEqual(ds['sda']['model'], 'Flash Disk')
        self.assertEqual(ds['sda']['parts'][0]['label'], 'DATA')

    def test_separate_boot_partition_marks_its_disk(self):
        ds = {d['name']: d for d in sysclone.disks(TREE, '/dev/mmcblk1p2', boot_part='/dev/sda1')}
        self.assertTrue(ds['sda']['system'])

    def test_min_partition_formula_matches_the_script(self):
        used = 5000 * sysclone.MB
        self.assertEqual(sysclone.min_partition_mb(used), (5000 + 300) * 100 // 95 + 1)

    def test_image_name(self):
        with mock.patch('socket.gethostname', return_value='slot 0'):
            self.assertRegex(sysclone.image_name('rel_1.2'), r'^slot_0_rel_1\.2_\d{8}_\d{6}\.img$')
            self.assertRegex(sysclone.image_name(''), r'^slot_0_\d{8}_\d{6}\.img$')
        with self.assertRaises(sysclone.CloneError):
            sysclone.image_name('../x')


class Jobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.base = config.BASE_DIR
        os.makedirs(os.path.join(self.tmp, 'tools'))
        path = os.path.join(self.tmp, 'tools', 'clone-system.sh')
        with open(path, 'w') as f:
            f.write(FAKE_SCRIPT)
        os.chmod(path, 0o755)
        config.BASE_DIR = self.tmp
        sysclone._job = None
        self.patches = [mock.patch('os.geteuid', return_value=0),
                        mock.patch.object(sysclone, 'disks', return_value=sysclone.disks(TREE, '/dev/mmcblk0p1'))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        if sysclone._job and sysclone._job.state == 'running':
            sysclone.stop()
            self._wait()
        config.BASE_DIR = self.base
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _wait(self, t=10):
        end = time.time() + t
        while time.time() < end and sysclone._job.state in ('running', 'stopping'):
            time.sleep(0.05)
        return sysclone.job_status()

    def test_clone_refuses_system_unknown_and_unconfirmed(self):
        for disk, confirm in [('mmcblk0', 'mmcblk0'), ('nope', 'nope'), ('mmcblk1', 'mmcblk2'), ('mmcblk1', ''),
                              ('sda', 'sda')]:                                  # sda1 is mounted
            with self.subTest(disk=disk), self.assertRaises(sysclone.CloneError):
                sysclone.start_clone(disk, 512, confirm=confirm)

    def test_needs_root(self):
        with mock.patch('os.geteuid', return_value=1000), self.assertRaises(sysclone.CloneError) as cm:
            sysclone.start_clone('mmcblk1', 512, confirm='mmcblk1')
        self.assertEqual(cm.exception.status, 403)

    def test_clone_runs_the_script_with_env_and_parses_progress(self):
        sysclone.start_clone('mmcblk1', 512, confirm='mmcblk1', grow=True)
        st = self._wait()
        self.assertEqual(st['state'], 'ok', st['lines'])
        self.assertIn('==> target /dev/mmcblk1 extra=512 size= grow=yes compress=', st['lines'])
        self.assertEqual(st['progress']['percent'], 95)                       # \r updates kept as progress only
        self.assertFalse(any('xfr#' in ln for ln in st['lines']))
        self.assertEqual(st['result'], '/dev/mmcblk11')
        self.assertEqual(sysclone.job_status(st['next'] - 1)['lines'], ['[exit code 0]'])

    def test_whole_disk_and_busy(self):
        with mock.patch.dict(os.environ, {'SLOW': '1'}):
            sysclone.start_clone('mmcblk1', 512, whole=True, confirm='mmcblk1', grow=True)
        with self.assertRaises(sysclone.CloneError) as cm:
            sysclone.start_clone('mmcblk1', 0, confirm='mmcblk1')
        self.assertEqual(cm.exception.status, 409)
        self.assertIn('size=max grow=no', sysclone.job_status()['lines'][1])
        sysclone.stop()
        self.assertEqual(self._wait()['state'], 'stopped')

    def test_failure_is_reported(self):
        with mock.patch.dict(os.environ, {'FAIL': 'yes'}):
            sysclone.start_clone('mmcblk1', 0, confirm='mmcblk1')
        st = self._wait()
        self.assertEqual((st['state'], st['rc']), ('error', 3))
        self.assertIn('ERROR: boom', st['lines'])

    def test_image_goes_into_the_share_folder(self):
        share = tempfile.mkdtemp()
        os.mkdir(os.path.join(share, 'images'))
        with mock.patch.object(smb, 'MOUNT_POINT', share), mock.patch.object(smb, 'status', return_value={'mounted': True}):
            sysclone.start_image('images', 2048, 'rel', 'gz', True)
            with self.assertRaises(sysclone.CloneError):
                sysclone.start_image('missing', 0)
        st = self._wait()
        self.assertRegex(st['lines'][1], rf'^==> target {share}/images/.+_rel_\d{{8}}_\d{{6}}\.img extra=2048 size= grow=yes compress=gz$')
        shutil.rmtree(share)


class Share(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, 'images', 'old'))
        with open(os.path.join(self.root, 'images', 'a.img'), 'wb') as f:
            f.write(b'x' * 10)
        os.symlink('/etc', os.path.join(self.root, 'escape'))
        self.patches = [mock.patch.object(smb, 'MOUNT_POINT', self.root),
                        mock.patch.object(smb, 'status', return_value={'mounted': True})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.root)

    def test_parse_share(self):
        for text, want in [('//192.168.1.5/NAS_drive', ('192.168.1.5', 'NAS_drive', '')),
                           ('smb://nas.local/share/images/x', ('nas.local', 'share', 'images/x')),
                           ('\\\\nas\\data\\img', ('nas', 'data', 'img'))]:
            self.assertEqual(smb.parse_share(text), want)
        for bad in ['', '//host', 'smb://-bad/share', '//h/sh*re', '//h/s/../x']:
            with self.subTest(bad=bad), self.assertRaises(smb.SmbError):
                smb.parse_share(bad)

    def test_mount_options_escape_and_validate(self):
        o = smb.build_options('nas', '10.0.0.2', 'data', 'vanya', 'p,w', '3.0')
        self.assertIn('pass=p,,w,', o)
        self.assertIn('unc=\\\\nas\\data', o)
        self.assertIn('vers=3.0', o)
        self.assertNotIn('guest', o)
        self.assertIn('guest', smb.build_options('nas', '10.0.0.2', 'data', '', '', ''))
        for user, vers in [('a,b', ''), ('a=b', ''), ('u', '9.9')]:
            with self.assertRaises(smb.SmbError):
                smb.build_options('nas', '1.1.1.1', 'd', user, 'p', vers)

    def test_mount_needs_root(self):
        with mock.patch('os.geteuid', return_value=1000), self.assertRaises(smb.SmbError) as cm:
            smb.mount('//nas/data', 'u', 'p')
        self.assertEqual(cm.exception.status, 403)

    def test_mount_remembers_settings_password_only_on_request(self):
        with mock.patch('os.geteuid', return_value=0), mock.patch.object(smb, '_sys_mount') as m, \
                mock.patch('socket.gethostbyname', return_value='10.0.0.9'), mock.patch.object(smb, 'umount'):
            smb.mount('//nas/data/img', 'vanya', 'secret', '3.0', remember=False)
            self.assertEqual(m.call_args[0][:3], ('//nas/data', self.root, 'cifs'))
            self.assertIn('ip=10.0.0.9', m.call_args[0][3])
            self.assertEqual(credentials.smb(), {'share': '//nas/data/img', 'username': 'vanya', 'password': '', 'vers': '3.0'})
            smb.mount('//nas/data/img', 'vanya', 'secret', '3.0', remember=True)
            self.assertEqual(credentials.smb()['password'], 'secret')
            self.assertEqual(credentials.smb_public()['password_set'], True)
            self.assertNotIn('password', credentials.smb_public())
            smb.mount('//nas/data/img', 'vanya', None, '3.0', remember=True)     # empty field = the saved one
            self.assertIn('pass=secret,', m.call_args[0][3])
            smb.forget()
            self.assertEqual(credentials.smb()['password'], '')

    def test_listdir_and_traversal(self):
        d = smb.listdir('')
        self.assertEqual([(i['name'], i['type']) for i in d['items']], [('images', 'dir'), ('escape', 'link')])
        self.assertEqual(d['items'][1]['target'], '/etc')
        d = smb.listdir('images')
        self.assertEqual([(i['name'], i['size']) for i in d['items']], [('old', None), ('a.img', 10)])
        self.assertEqual(d['path'], 'images')
        for bad in ['../', 'images/../../etc', 'escape']:
            with self.subTest(bad=bad), self.assertRaises(smb.SmbError):
                smb.listdir(bad)

    def test_mkdir(self):
        smb.mkdir('images', 'new')
        self.assertTrue(os.path.isdir(os.path.join(self.root, 'images', 'new')))
        for bad in ['', '..', 'a/b']:
            with self.subTest(bad=bad), self.assertRaises(smb.SmbError):
                smb.mkdir('images', bad)
        with self.assertRaises(smb.SmbError):
            smb.mkdir('images', 'new')

    def test_api(self):
        self.assertEqual(client().get('/api/smb/list').status_code, 401)
        c = client(logged_in=True)
        r = c.get('/api/smb/list?path=images')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get('/api/smb/list?path=../x').status_code, 400)
        with mock.patch('os.geteuid', return_value=1000):
            self.assertEqual(c.post('/api/smb/mount', json={'share': '//nas/x'}).status_code, 403)
            self.assertEqual(c.post('/api/sysclone/clone', json={'disk': 'zzz'}).status_code, 404)


class WriteImage(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, 'imgs', 'deep', '.hidden'))
        for rel, size in [('imgs/a.img', 100), ('imgs/b.img.gz', 50), ('imgs/notes.txt', 5), ('imgs/deep/c.img.xz', 70),
                          ('imgs/deep/.hidden/d.img', 10), ('big.img', 20_000_000_000)]:
            with open(os.path.join(self.root, rel), 'wb') as f:
                f.truncate(size)
        os.symlink('/etc', os.path.join(self.root, 'imgs', 'out'))
        self.patches = [mock.patch.object(sysclone, 'image_roots', return_value=[{'path': os.path.realpath(self.root), 'label': 't', 'kind': 'home'}]),
                        mock.patch.object(sysclone, 'disks', return_value=sysclone.disks(TREE, '/dev/mmcblk0p1')),
                        mock.patch.object(sysclone, '_start', side_effect=lambda *a, **k: {'args': a, 'kw': k})]
        for p in self.patches:
            p.start()
        self.r = os.path.realpath(self.root)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.root)

    def test_roots_from_share_disks_and_homes(self):
        self.patches[0].stop()
        try:
            with mock.patch.object(smb, 'status', return_value={'mounted': False}):
                roots = sysclone.image_roots(sysclone.disks(TREE, '/dev/mmcblk0p1'))
            kinds = {r['kind'] for r in roots}
            self.assertNotIn('share', kinds)
            self.assertIn(os.path.realpath('/media/usb') if os.path.isdir('/media/usb') else None,
                          [r['path'] for r in roots] + [None])                      # only existing folders
            self.assertFalse(any(r['path'] == '/' for r in roots))
        finally:
            self.patches[0].start()

    def test_browse_lists_folders_and_images_only(self):
        d = sysclone.browse_images(self.r, 'imgs')
        self.assertEqual([x['name'] for x in d['dirs']], ['deep', 'out'])
        self.assertEqual(sorted(x['name'] for x in d['images']), ['a.img', 'b.img.gz'])
        self.assertEqual(d['path'], 'imgs')
        for bad in ['../', 'imgs/out', 'imgs/../..']:
            with self.subTest(bad=bad), self.assertRaises(sysclone.CloneError):
                sysclone.browse_images(self.r, bad)
        with self.assertRaises(sysclone.CloneError) as cm:
            sysclone.browse_images('/etc', '')
        self.assertEqual(cm.exception.status, 404)

    def test_find_below_a_folder(self):
        d = sysclone.find_images(self.r, 'imgs')
        self.assertEqual(sorted(x['path'] for x in d['images']), ['imgs/a.img', 'imgs/b.img.gz', 'imgs/deep/c.img.xz'])
        self.assertFalse(d['truncated'])

    def test_write_validation(self):
        r = sysclone.start_write(self.r, 'imgs/b.img.gz', 'mmcblk1', 'mmcblk1')
        self.assertEqual(r['args'][2], {'IMAGE': os.path.join(self.r, 'imgs/b.img.gz'), 'TARGET_DISK': '/dev/mmcblk1'})
        self.assertEqual(r['kw'], {'name': 'write-image.sh', 'total': 50})
        for path, disk, confirm in [('imgs/notes.txt', 'mmcblk1', 'mmcblk1'), ('imgs/a.img', 'mmcblk0', 'mmcblk0'),
                                    ('imgs/a.img', 'sda', 'sda'), ('imgs/a.img', 'mmcblk1', 'x'), ('big.img', 'mmcblk1', 'mmcblk1'),
                                    ('../etc/passwd', 'mmcblk1', 'mmcblk1')]:
            with self.subTest(path=path, disk=disk), self.assertRaises(sysclone.CloneError):
                sysclone.start_write(self.r, path, disk, confirm)

    def test_dd_progress(self):
        job = sysclone.Job('write', 't', {}, total=1000)
        job.add('500 bytes (500 B) copied, 2 s, 250 B/s')
        self.assertEqual(job.progress['percent'], 50)
        self.assertEqual(job.progress['eta'], '0:00:02')
        job.add('==> Done: image written to /dev/sda')
        self.assertEqual(job.result, '/dev/sda')


class Script(unittest.TestCase):
    PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools', 'clone-system.sh')

    PATHS = [PATH, PATH.replace('clone-system.sh', 'write-image.sh')]

    def test_syntax_and_executable(self):
        for p in self.PATHS:
            self.assertTrue(os.access(p, os.X_OK), p)
            r = subprocess.run(['bash', '-n', p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_refuses_without_root(self):
        if os.geteuid() == 0:
            self.skipTest('running as root')
        for p in self.PATHS:
            r = subprocess.run(['bash', p], capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', 'NO_COLOR': '1'})
            self.assertEqual(r.returncode, 1, p)
            self.assertIn('run with sudo', r.stderr)


if __name__ == '__main__':
    unittest.main()
