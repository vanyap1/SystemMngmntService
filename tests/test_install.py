"""install.sh and tools/offline_bundle.py: syntax, component lists in sync, index helpers. No network, no root."""
import os
import re
import subprocess
import tempfile
import unittest

from tests.support import ROOT

import contextlib
import importlib.util
import io
_spec = importlib.util.spec_from_file_location('offline_bundle', os.path.join(ROOT, 'tools', 'offline_bundle.py'))
ob = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ob)

INSTALL = os.path.join(ROOT, 'install.sh')
with open(INSTALL) as _fh:
    INSTALL_TEXT = _fh.read()

INDEX = """Package: bsdutils
Essential: yes
Priority: required
Architecture: armhf
Version: 1:2.38.1-5+deb12u3
Filename: pool/main/u/util-linux/bsdutils_2.38.1-5+deb12u3_armhf.deb
Size: 10
Description-md5: aa

Package: bsdutils
Essential: yes
Priority: required
Architecture: armhf
Version: 1:2.38.1-5+b1
Filename: pool/main/u/util-linux/bsdutils_2.38.1-5+b1_armhf.deb

Package: git
Priority: optional
Architecture: armhf
Version: 1:2.39.5-0+deb12u3
Depends: libc6 (>= 2.34),
 perl
Filename: pool/main/g/git/git_2.39.5-0+deb12u3_armhf.deb

Package: python3
Priority: optional
Architecture: armhf
Version: 3.11.2-1+b1
Provides: python3-profiler
Filename: pool/main/p/python3/python3_3.11.2-1+b1_armhf.deb
"""


def sh(script, *args):
    return subprocess.run(['bash', '-c', script, 'test', *args], capture_output=True, text=True)


class Installer(unittest.TestCase):
    def test_syntax(self):
        for f in ('install.sh', 'setup.sh', 'setup_offline.sh'):
            r = subprocess.run(['bash', '-n', os.path.join(ROOT, f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f + r.stderr)

    def test_components_in_sync(self):
        """install.sh's PKGS must match COMPONENTS of the bundle builder."""
        text = INSTALL_TEXT
        block = re.search(r'declare -A PKGS=\((.*?)\n\)', text, re.S).group(1)
        pkgs = {k: v.split() for k, v in re.findall(r'\[(\w+)\]="([^"]*)"', block)}
        self.assertEqual(pkgs, ob.COMPONENTS)
        wheels = re.search(r'WHEELS=\(([^)]*)\)', text).group(1).replace('"', '').split()
        self.assertEqual(wheels, ob.WHEELS)

    def test_help_and_errors(self):
        r = subprocess.run([INSTALL, '--help'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn('install.sh bundle', r.stdout)
        r = subprocess.run([INSTALL, 'bogus'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('unknown argument', r.stderr)
        r = subprocess.run([INSTALL], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)                # no terminal → no menu

    def test_status_runs(self):
        r = subprocess.run([INSTALL, 'status'], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('Components', r.stdout)
        self.assertIn('This machine needs:', r.stdout)

    def test_manifest_list_and_selection(self):
        """The offline path parses manifest.json with sed (python may be missing before the install)."""
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
            fh.write('{\n  "suite": "bookworm",\n  "components": [\n    "core",\n    "git"\n  ],\n'
                     '  "packages": [\n    "python3",\n    "git"\n  ],\n  "debs": 3\n}')
        try:
            funcs = re.search(r'(selected_pkgs\(\).*?\n}\n\nmanifest_list\(\).*?\n}\n)', INSTALL_TEXT, re.S).group(1)
            head = re.search(r'(declare -A PKGS=\(.*?\n\))', INSTALL_TEXT, re.S).group(1)
            r = sh(head + '\n' + funcs + '\nmanifest_list "$1" components; manifest_list "$1" packages;'
                   'COMPONENTS=core,git; selected_pkgs "python3 git"', fh.name)
        finally:
            os.remove(fh.name)
        self.assertEqual(r.stdout.split('\n')[:3], ['core,git', 'python3,git', ' python3 git'])


class Bundle(unittest.TestCase):
    def setUp(self):
        self.st = ob.parse_packages(INDEX)

    def test_parse_keeps_continuation(self):
        git = [f for f in self.st if f['Package'] == 'git'][0]
        self.assertIn('perl', git['Depends'])
        self.assertEqual(len(self.st), 4)

    def test_base_status_oldest_version_no_depends(self):
        status = ob.base_status(self.st)
        self.assertIn('Version: 1:2.38.1-5+b1', status)          # oldest of the two bsdutils builds
        self.assertNotIn('deb12u3', status)
        self.assertNotIn('git', status)                          # not a base package
        self.assertNotIn('Depends', status)
        self.assertIn('Status: install ok installed', status)

    def test_local_index_matches_epoch_names(self):
        names, text = ob.local_index(self.st, ['bsdutils_1%3a2.38.1-5+deb12u3_armhf.deb', 'git_1%3a2.39.5-0+deb12u3_armhf.deb'])
        self.assertEqual(names['bsdutils_1%3a2.38.1-5+deb12u3_armhf.deb'], 'bsdutils_2.38.1-5+deb12u3_armhf.deb')
        self.assertIn('Filename: ./git_2.39.5-0+deb12u3_armhf.deb', text)
        self.assertIn(' perl', text)                             # multi-line field kept
        self.assertNotIn('pool/', text)
        self.assertNotIn('Description-md5', text)
        with self.assertRaises(SystemExit):
            ob.local_index(self.st, ['missing_1.0_armhf.deb'])

    def test_python_version(self):
        self.assertEqual(ob.python_version(self.st), '3.11')

    def test_known_uses_provides(self):
        ok, missing = ob.AptTarget.known(None, self.st, ['git', 'python3-profiler', 'nope'])
        self.assertEqual((ok, missing), (['git', 'python3-profiler'], ['nope']))

    def test_cli_validation(self):
        for args in (['--arch', 'mips'], ['--components', 'nope'], ['--suite', 'x/../y']):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                ob.main(args)


if __name__ == '__main__':
    unittest.main()
