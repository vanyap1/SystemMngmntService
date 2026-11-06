"""Top bar sections (core/nav.py) and the lazily loaded file tree of the code editor (/api/tree)."""
import os
import tempfile
import unittest

from tests.support import TMP, client, config  # noqa: F401  (support first)
from core import nav
from routes import editor


class Sections(unittest.TestCase):
    def test_every_nav_endpoint_exists(self):
        from app import app
        rules = {r.endpoint for r in app.url_map.iter_rules()}
        for ep in nav.endpoints():
            self.assertIn(ep, rules)

    def test_logs_live_in_tests_section(self):
        tests = [s for s in nav.sections(True, 'logs.logs') if s['id'] == 'tests'][0]
        self.assertTrue(tests['active'])
        self.assertEqual([p['endpoint'] for p in tests['pages']], ['tests.tests', 'logs.logs'])
        self.assertEqual([p['active'] for p in tests['pages']], [False, True])

    def test_anonymous_sees_main_only(self):
        self.assertEqual([s['id'] for s in nav.sections(False, 'dashboard.index')], ['main'])

    def test_section_subtabs_rendered(self):
        c = client(logged_in=True)
        html = c.get('/logs').get_data(as_text=True)
        self.assertIn('tb-sec-group', html)
        self.assertIn('class="tb-sub active"', html)
        self.assertIn('href="/tests"', html)
        main = c.get('/').get_data(as_text=True)
        self.assertNotIn('tb-sec-group', main)                    # closed section = one link
        self.assertIn('class="tb-sec active"', main)

    def test_power_menu_holds_logout(self):
        html = client(logged_in=True).get('/').get_data(as_text=True)
        menu = html[html.index('id="power-dropdown"'):]
        self.assertIn('/logout', menu[:menu.index('</div>\n</div>')])


class LazyTree(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(self.root, 'a', 'deep', 'deeper'))
        for rel in ('a/x.txt', 'a/deep/y.txt', 'b.txt', '.hidden'):
            with open(os.path.join(self.root, rel), 'w') as f:
                f.write('1')
        self._saved = config.CFG['target_dir']
        config.CFG['target_dir'] = self.root
        self.c = client(logged_in=True)

    def tearDown(self):
        config.CFG['target_dir'] = self._saved

    def test_one_level_at_a_time(self):
        d = self.c.get('/api/tree').get_json()
        self.assertEqual([(e['name'], e['type']) for e in d['entries']], [('a', 'dir'), ('b.txt', 'file')])
        self.assertNotIn('children', d['entries'][0])
        sub = self.c.get('/api/tree?path=' + os.path.join(self.root, 'a')).get_json()
        self.assertEqual([e['name'] for e in sub['entries']], ['deep', 'x.txt'])
        self.assertFalse(sub['truncated'])

    def test_outside_target_dir_refused(self):
        for p in ('/etc', self.root + '/../', self.root + '/a/../../'):
            with self.subTest(p=p):
                self.assertEqual(self.c.get('/api/tree?path=' + p).status_code, 403)
        self.assertEqual(self.c.get('/api/tree?path=' + os.path.join(self.root, 'b.txt')).status_code, 404)

    def test_symlink_out_is_listed_but_not_opened(self):
        os.symlink('/etc', os.path.join(self.root, 'etc-link'))
        e = [x for x in self.c.get('/api/tree').get_json()['entries'] if x['name'] == 'etc-link'][0]
        self.assertEqual((e['type'], e['link']), ('dir', True))
        self.assertEqual(self.c.get('/api/tree?path=' + e['path']).status_code, 403)

    def test_truncated(self):
        saved, editor.TREE_LIMIT = editor.TREE_LIMIT, 1
        try:
            d = self.c.get('/api/tree').get_json()
        finally:
            editor.TREE_LIMIT = saved
        self.assertEqual(len(d['entries']), 1)
        self.assertTrue(d['truncated'])


if __name__ == '__main__':
    unittest.main()
