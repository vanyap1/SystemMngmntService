"""The panel must work in a closed network: no CDN/external URLs, vendored libraries present."""
import os
import re
import unittest

from tests.support import ROOT, client

EXTERNAL = re.compile(r'''(?:src|href)\s*=\s*["']\s*(?:https?:)?//|url\(\s*["']?(?:https?:)?//|["'`]https?://(?!www\.w3\.org)''')
VENDORED = ['fontawesome/css/all.min.css', 'fontawesome/webfonts/fa-solid-900.woff2',
            'fontawesome/webfonts/fa-regular-400.woff2', 'fontawesome/webfonts/fa-brands-400.woff2',
            'monaco/vs/loader.js', 'monaco/vs/editor/editor.main.js', 'monaco/vs/base/worker/workerMain.js',
            'xterm/xterm.js', 'xterm/xterm.css', 'xterm/xterm-addon-fit.js']


class Offline(unittest.TestCase):
    def test_no_external_urls_in_sources(self):
        bad = []
        for sub in ('templates', 'static'):
            for dirpath, dirs, files in os.walk(os.path.join(ROOT, sub)):
                dirs[:] = [d for d in dirs if d != 'vendor']
                for name in files:
                    if name.endswith(('.html', '.js', '.css')):
                        path = os.path.join(dirpath, name)
                        with open(path, encoding='utf-8') as f:
                            for n, line in enumerate(f, 1):
                                if EXTERNAL.search(line):
                                    bad.append(f'{os.path.relpath(path, ROOT)}:{n}: {line.strip()[:100]}')
        self.assertEqual(bad, [], 'external URLs found — vendor the library into static/vendor')

    def test_vendored_files_are_served(self):
        c = client()
        for rel in VENDORED:
            with self.subTest(file=rel):
                self.assertTrue(os.path.isfile(os.path.join(ROOT, 'static', 'vendor', rel)))
                r = c.get('/static/vendor/' + rel)
                self.assertEqual(r.status_code, 200)
                r.close()

    def test_rendered_pages_have_no_external_urls(self):
        c = client(logged_in=True)
        for url in ['/', '/editor', '/settings', '/tests', '/login']:
            with self.subTest(url=url):
                html = c.get(url).get_data(as_text=True)
                self.assertIsNone(EXTERNAL.search(html), EXTERNAL.search(html) and html[EXTERNAL.search(html).start():][:120])


if __name__ == '__main__':
    unittest.main()
