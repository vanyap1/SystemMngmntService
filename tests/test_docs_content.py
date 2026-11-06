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

    def test_test_platform_doc_covers_watch_and_psu(self):
        with open(os.path.join(HELP, 'testing', 'test-platform.md'), encoding='utf-8') as fh:
            doc = fh.read()
        with open(os.path.join(HELP, 'testing', 'psu.md'), encoding='utf-8') as fh:
            docs = {'testWatch.py': doc, 'instruments/psu.py': fh.read()}
        # skip: lifecycle called by ts.run(), the self-test function in __main__
        for module, skip in (('testWatch.py', {'start', 'stop', 'close', 'button'}), ('instruments/psu.py', {'close'})):
            with open(os.path.join(ROOT, 'testPlatform', module), encoding='utf-8') as fh:
                public = set(re.findall(r'^    def ([a-z]\w*)\(', fh.read(), re.M)) - skip
            missing = sorted(m for m in public if m + '(' not in docs[module] and '.' + m not in docs[module])
            with self.subTest(module=module):
                self.assertEqual(missing, [], f'{module} methods not described in help/testing/')


if __name__ == '__main__':
    unittest.main()
