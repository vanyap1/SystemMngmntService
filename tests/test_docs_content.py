"""The documentation shipped in help/ (the real folder, read-only): every relative image / page / file link exists."""
import os
import re
import unittest

from tests.support import ROOT

HELP = os.path.join(ROOT, 'help')
LINK = re.compile(r'!?\[[^\]]*\]\(([^)\s]+)\)')
SKIP_DIRS = {'examples', '.trash', 'blkDiagExamples'}


class DocLinks(unittest.TestCase):
    def test_relative_links_resolve(self):
        bad = []
        for dirpath, dirs, files in os.walk(HELP):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if not name.endswith('.md'):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8') as fh:
                    text = fh.read()
                text = re.sub(r'```.*?```', '', text, flags=re.S)        # examples in code blocks
                text = re.sub(r'`[^`\n]*`', '', text)
                for href in LINK.findall(text):
                    if re.match(r'^([a-z]+:|#|/)', href):
                        continue
                    target = os.path.normpath(os.path.join(dirpath, href.split('#')[0]))
                    if not os.path.exists(target):
                        bad.append(f'{os.path.relpath(path, HELP)}: {href}')
        self.assertEqual(bad, [])

    def test_test_platform_doc_covers_the_api(self):
        with open(os.path.join(HELP, 'testing', 'test-platform.md'), encoding='utf-8') as fh:
            doc = fh.read()
        with open(os.path.join(ROOT, 'testPlatform', 'testStrategy.py'), encoding='utf-8') as fh:
            src = fh.read()
        public = re.findall(r'^    def ([a-z]\w*)\(', src, re.M)
        missing = [m for m in public if m not in doc]
        self.assertEqual(missing, [], 'TestStrategy methods not described in help/testing/test-platform.md')

    def test_instrument_pages_cover_every_public_function(self):
        pages = {'rigol_dho.py': 'rigol-dho.md', 'owon_xdm.py': 'owon-xdm.md', 'owon_oel.py': 'owon-oel.md',
                 'serial_term.py': 'serial-term.md', 'ssh_term.py': 'ssh-term.md', 'param_file.py': 'param-file.md',
                 'psu_custom305.py': 'psu-custom305.md', 'modbus.py': 'modbus.md',
                 'scpi.py': 'instruments.md'}
        skip = {'scpi.py': {'open', 'readline', 'read_exact', 'drain'}}        # transport internals
        for module, page in pages.items():
            with open(os.path.join(HELP, 'testing', page), encoding='utf-8') as fh:
                doc = fh.read()
            with open(os.path.join(ROOT, 'testPlatform', 'instruments', module), encoding='utf-8') as fh:
                public = set(re.findall(r'^    def ([a-z]\w*)\(', fh.read(), re.M)) - skip.get(module, set())
            missing = sorted(m for m in public if m + '(' not in doc and '.' + m not in doc)
            with self.subTest(module=module):
                self.assertEqual(missing, [], f'instruments/{module} functions not described in help/testing/{page}')

    def test_every_driver_file_is_in_the_catalog(self):
        with open(os.path.join(HELP, 'testing', 'instruments.md'), encoding='utf-8') as fh:
            doc = fh.read()
        folder = os.path.join(ROOT, 'testPlatform', 'instruments')
        files = sorted(f for f in os.listdir(folder) if f.endswith('.py') and f != '__init__.py')
        self.assertEqual([f for f in files if f'`{f}`' not in doc], [], 'drivers missing in help/testing/instruments.md')

    def test_test_platform_doc_covers_watch_and_psu(self):
        with open(os.path.join(HELP, 'testing', 'test-platform.md'), encoding='utf-8') as fh:
            doc = fh.read()
        with open(os.path.join(HELP, 'testing', 'psu-custom6020.md'), encoding='utf-8') as fh:
            docs = {'testWatch.py': doc, 'instruments/psu_custom6020.py': fh.read()}
        # skip: lifecycle called by ts.run(), the self-test function in __main__
        for module, skip in (('testWatch.py', {'start', 'stop', 'close', 'button'}), ('instruments/psu_custom6020.py', {'close'})):
            with open(os.path.join(ROOT, 'testPlatform', module), encoding='utf-8') as fh:
                public = set(re.findall(r'^    def ([a-z]\w*)\(', fh.read(), re.M)) - skip
            missing = sorted(m for m in public if m + '(' not in docs[module] and '.' + m not in docs[module])
            with self.subTest(module=module):
                self.assertEqual(missing, [], f'{module} methods not described in help/testing/')


if __name__ == '__main__':
    unittest.main()
