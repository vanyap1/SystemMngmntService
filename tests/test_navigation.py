"""Top bar sections (core/nav.py), the lazily loaded file tree of the code editor (/api/tree) and creating files /
folders in it (/api/file_create)."""
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


class CreateEntries(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(self.root, 'testPlatform'))
        self._saved = config.CFG['target_dir']
        config.CFG['target_dir'] = self.root
        self.c = client(logged_in=True)

    def tearDown(self):
        config.CFG['target_dir'] = self._saved

    def create(self, **body):
        return self.c.post('/api/file_create', json=body)

    def test_file_in_a_subfolder_and_test_skeleton(self):
        tp = os.path.join(self.root, 'testPlatform')
        r = self.create(dir=tp, name='psu_check_test.py')
        self.assertEqual(r.status_code, 200)
        path = r.get_json()['path']
        self.assertEqual(path, os.path.join(tp, 'psu_check_test.py'))
        text = open(path).read()
        self.assertTrue(text.startswith('"""Psu check: '))
        self.assertIn('ts.run(steps, finalize)', text)
        compile(text, path, 'exec')
        self.assertEqual(open(self.create(dir=tp, name='notes.txt').get_json()['path']).read(), '')
        self.assertEqual(self.create(dir=tp, name='notes.txt').status_code, 409)

    def test_folder_then_file_inside_and_root_default(self):
        r = self.create(dir=os.path.join(self.root, 'testPlatform'), name='station2', kind='dir')
        self.assertEqual(r.get_json()['kind'], 'dir')
        sub = r.get_json()['path']
        self.assertTrue(os.path.isdir(sub))
        self.assertEqual(self.create(dir=sub, name='a.py').status_code, 200)
        self.assertTrue(os.path.isfile(os.path.join(self.root, self.create(name='top.txt').get_json()['name'])))

    def test_refused(self):
        for body, code in (({'dir': '/etc', 'name': 'x'}, 403), ({'dir': self.root + '/..', 'name': 'x'}, 403),
                           ({'name': ''}, 400), ({'name': '.hidden'}, 400), ({'name': '..'}, 400),
                           ({'dir': os.path.join(self.root, 'missing'), 'name': 'x'}, 404)):
            with self.subTest(body=body):
                self.assertEqual(self.create(**body).status_code, code)
        self.assertEqual(self.create(name='../escape.txt').status_code, 400)
        r = self.create(name='a/../b.txt')                    # the name is cleaned, never a path
        self.assertEqual(r.get_json()['name'], 'a_.._b.txt')
        self.assertEqual(os.path.dirname(r.get_json()['path']), os.path.realpath(self.root))


if __name__ == '__main__':
    unittest.main()
