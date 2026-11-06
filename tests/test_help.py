"""Documentation store (core/help_docs.py) and /api/help/* routes; help_dir is a temp dir (tests/support.py)."""
import io
import json
import os
import shutil
import unittest

from tests.support import client, config  # noqa: F401  (support first)
from core import help_docs
from core.help_docs import DocError


def _reset():
    shutil.rmtree(help_docs.root(), ignore_errors=True)
    os.makedirs(help_docs.root())


def _write(rel, text):
    full = os.path.join(help_docs.root(), rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w', encoding='utf-8') as f:
        f.write(text)


class Paths(unittest.TestCase):
    def test_valid(self):
        for raw, want in [('a', 'a.md'), ('linux/udev.md', 'linux/udev.md'), ('Мережа/налаштування', 'Мережа/налаштування.md'),
                          ('/x/y.md/', 'x/y.md'), ('a b (1).md', 'a b (1).md'), ('x\\y', 'x/y.md')]:
            with self.subTest(raw=raw):
                self.assertEqual(help_docs.check_doc_path(raw), want)

    def test_invalid(self):
        for raw in ['', '../x', 'a/../b', '.hidden', 'img/x', 'docs/x', 'examples/x', 'a/b/c/d/e.md', 'x/.md',
                    'a<b', 'a:b', 'a\x00b', '.trash/x']:
            with self.subTest(raw=raw):
                with self.assertRaises(DocError):
                    help_docs.check_doc_path(raw)

    def test_safe_file_name(self):
        self.assertEqual(help_docs.safe_file_name('../../etc/passwd'), 'passwd')
        self.assertEqual(help_docs.safe_file_name('My Photo (1).PNG'), 'My_Photo_1.png')
        self.assertEqual(help_docs.safe_file_name('схема живлення.png'), 'схема_живлення.png')
        self.assertEqual(help_docs.safe_file_name('...'), 'file')

    def test_relink(self):
        md = '![a](img/x.png) [f](docs/f.zip) <img src="img/y.png"> [ext](http://h/img/z) [p](other.md)'
        down = help_docs.relink(md, 0, 2)
        self.assertIn('](../../img/x.png)', down)
        self.assertIn('](../../docs/f.zip)', down)
        self.assertIn('src="../../img/y.png"', down)
        self.assertIn('(http://h/img/z)', down)
        self.assertEqual(help_docs.relink(down, 2, 0), md)


class Store(unittest.TestCase):
    def setUp(self):
        _reset()

    def test_list_skips_reserved_and_hidden(self):
        _write('index.md', '# Start\n')
        _write('linux/udev.md', 'no heading')
        _write('img/x.md', '# not a page')
        _write('docs/y.md', '# not a page')
        _write('examples/z.md', '# not a page')
        _write('.trash/old.md', '# deleted')
        _write('linux/notes.txt', 'not markdown')
        docs = {d['path']: d['title'] for d in help_docs.list_docs()}
        self.assertEqual(docs, {'index.md': 'Start', 'linux/udev.md': 'udev'})

    def test_create_save_conflict(self):
        d = help_docs.create_doc('net/ssh', 'SSH keys')
        self.assertEqual(d['path'], 'net/ssh.md')
        with self.assertRaises(DocError) as e:
            help_docs.create_doc('net/ssh.md')
        self.assertEqual(e.exception.status, 409)
        doc = help_docs.read_doc('net/ssh.md')
        self.assertEqual(doc['title'], 'SSH keys')
        saved = help_docs.save_doc('net/ssh.md', '# SSH\nnew', doc['mtime'])
        self.assertEqual(saved['title'], 'SSH')
        with self.assertRaises(DocError) as e:                      # stale mtime
            help_docs.save_doc('net/ssh.md', 'x', doc['mtime'] - 10)
        self.assertEqual(e.exception.status, 409)
        help_docs.save_doc('net/ssh.md', '# forced', doc['mtime'] - 10, force=True)
        self.assertEqual(help_docs.read_doc('net/ssh.md')['content'], '# forced')

    def test_rename_moves_and_relinks(self):
        _write('a.md', '# A\n![p](img/p.png)\n')
        r = help_docs.rename_doc('a.md', 'deep/er/b.md')
        self.assertEqual(r['path'], 'deep/er/b.md')
        self.assertIn('](../../img/p.png)', help_docs.read_doc('deep/er/b.md')['content'])
        help_docs.rename_doc('deep/er/b.md', 'c.md')
        self.assertFalse(os.path.exists(os.path.join(help_docs.root(), 'deep')))   # empty folders pruned
        self.assertIn('](img/p.png)', help_docs.read_doc('c.md')['content'])

    def test_delete_goes_to_trash(self):
        _write('x/y.md', '# Y')
        help_docs.delete_doc('x/y.md')
        self.assertEqual(help_docs.list_docs(), [])
        self.assertEqual(len(os.listdir(os.path.join(help_docs.root(), '.trash'))), 1)

    def test_search(self):
        _write('a.md', '# Network\nnetplan apply\n')
        _write('b.md', '# Other\nuse netplan here\nand ssh\n')
        res = help_docs.search('netplan')
        self.assertEqual([r['path'] for r in res], ['a.md', 'b.md'])
        self.assertEqual(res[1]['hits'][0], {'line': 2, 'text': 'use netplan here'})
        self.assertEqual([r['path'] for r in help_docs.search('netplan SSH')], ['b.md'])
        self.assertEqual(help_docs.search('network')[0]['path'], 'a.md')
        self.assertEqual(help_docs.search('  '), [])

    def test_file_path(self):
        _write('img/a.png', 'x')
        _write('.trash/s.md', 'x')
        self.assertTrue(help_docs.file_path('img/a.png'))
        for bad in ['../config.json', 'img/../../config.json', '.trash/s.md', 'img/missing.png', '', 'img//a.png']:
            with self.subTest(bad=bad):
                self.assertIsNone(help_docs.file_path(bad))


class Api(unittest.TestCase):
    def setUp(self):
        _reset()
        self.c = client(logged_in=True)

    def _upload(self, kind, name, data=b'data'):
        return self.c.post('/api/help/upload', data={'kind': kind, 'file': (io.BytesIO(data), name)},
                           content_type='multipart/form-data')

    def test_page(self):
        html = self.c.get('/help').get_data(as_text=True)
        self.assertIn('marked.min.js', html)
        self.assertIn('help.js', html)

    def test_crud(self):
        r = self.c.post('/api/help/create', json={'path': 'linux/udev', 'title': 'udev'})
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual([d['path'] for d in self.c.get('/api/help/tree').get_json()['docs']], ['linux/udev.md'])
        doc = self.c.get('/api/help/doc?path=linux/udev.md').get_json()
        r = self.c.post('/api/help/doc', json={'path': doc['path'], 'content': '# udev rules\n', 'mtime': doc['mtime']})
        self.assertEqual(r.get_json()['title'], 'udev rules')
        r = self.c.post('/api/help/doc', json={'path': doc['path'], 'content': 'x', 'mtime': doc['mtime'] - 5})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.c.post('/api/help/rename', json={'path': 'linux/udev.md', 'new_path': 'udev'}).get_json()['path'], 'udev.md')
        self.assertEqual(self.c.post('/api/help/delete', json={'path': 'udev.md'}).status_code, 200)
        self.assertEqual(self.c.get('/api/help/doc?path=udev.md').status_code, 404)

    def test_bad_requests(self):
        self.assertEqual(self.c.post('/api/help/create', json={'path': '../evil'}).status_code, 400)
        self.assertEqual(self.c.post('/api/help/create', json={'path': 'img/x'}).status_code, 400)
        self.assertEqual(self.c.get('/api/help/doc?path=nope.md').status_code, 404)
        self.assertEqual(self.c.get('/api/help/assets?kind=etc').status_code, 400)
        self.assertEqual(self.c.post('/api/help/upload', data={'kind': 'img'}).status_code, 400)
        self.assertEqual(self._upload('img', 'script.sh').status_code, 400)

    def test_upload_list_serve_delete(self):
        r = self._upload('img', 'My Pic.PNG', b'\x89PNG1')
        self.assertEqual(r.get_json()['names'], ['My_Pic.png'])
        self.assertEqual(self._upload('img', 'My Pic.png', b'\x89PNG1').get_json()['names'], ['My_Pic.png'])  # same file
        self.assertEqual(self._upload('img', 'My Pic.png', b'\x89PNG2').get_json()['names'], ['My_Pic-2.png'])
        self.assertEqual(self._upload('docs', 'tool.zip', b'PK').get_json()['names'], ['tool.zip'])
        _write('page.md', '# P\n![x](img/My_Pic.png)\n')
        items = {i['name']: i['used_by'] for i in self.c.get('/api/help/assets?kind=img').get_json()['items']}
        self.assertEqual(items, {'My_Pic.png': ['page.md'], 'My_Pic-2.png': []})

        r = self.c.get('/help/file/img/My_Pic.png')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, 'image/png')
        self.assertIn('sandbox', r.headers['Content-Security-Policy'])
        r.close()
        r = self.c.get('/help/file/docs/tool.zip?dl=1')
        self.assertIn('attachment', r.headers['Content-Disposition'])
        r.close()
        r = self.c.get('/help/file/page.md')
        self.assertTrue(r.mimetype.startswith('text/plain'))
        r.close()
        self.assertEqual(self.c.get('/help/file/../config.json').status_code, 404)

        self.assertEqual(self.c.post('/api/help/asset_delete', json={'kind': 'img', 'name': '../page.md'}).status_code, 400)
        self.assertEqual(self.c.post('/api/help/asset_delete', json={'kind': 'img', 'name': 'My_Pic-2.png'}).status_code, 200)
        self.assertEqual(self.c.get('/help/file/img/My_Pic-2.png').status_code, 404)


if __name__ == '__main__':
    unittest.main()


class Diagrams(unittest.TestCase):
    """core/diagrams.py + /api/help/diagram* (help_dir/diagrams/<name>.json + .svg)."""

    def setUp(self):
        _reset()
        self.c = client(logged_in=True)
        self.data = {'version': 1, 'title': 'Board', 'width': 100, 'height': 50,
                     'kinds': {'zz': {'label': 'last'}, 'aa': {'label': 'first'}}, 'items': []}

    def test_names(self):
        from core import diagrams
        self.assertEqual(diagrams.check_name('board_v2.json'), 'board_v2')
        self.assertEqual(diagrams.check_name('плата-1'), 'плата-1')
        for bad in ['', '../x', 'a/b', '.x', 'a b', 'x.']:
            with self.subTest(bad=bad), self.assertRaises(DocError):
                diagrams.check_name(bad)

    def test_crud_and_doc_links(self):
        body = json.dumps({'name': 'board', 'data': self.data, 'svg': '<svg></svg>'})   # json= would sort the keys
        r = self.c.post('/api/help/diagram/create', data=body, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.c.post('/api/help/diagram/create', json={'name': 'board', 'data': self.data}).status_code, 409)
        self.assertEqual([i['name'] for i in self.c.get('/api/help/diagrams').get_json()['items']], ['board'])
        self.assertNotIn('diagrams', [d['path'].split('/')[0] for d in help_docs.list_docs()])

        _write('hw/page.md', '# P\n![b](../diagrams/board.svg)\n')
        d = self.c.get('/api/help/diagram?name=board').get_json()
        self.assertEqual(list(d['data']['kinds']), ['zz', 'aa'])           # key order kept (legend order)
        self.assertEqual(d['used_by'], ['hw/page.md'])

        bad = self.c.post('/api/help/diagram/save', json={'name': 'board', 'data': self.data, 'svg': '<script>', 'mtime': d['mtime']})
        self.assertEqual(bad.status_code, 400)
        stale = self.c.post('/api/help/diagram/save', json={'name': 'board', 'data': self.data, 'mtime': d['mtime'] - 9})
        self.assertEqual(stale.status_code, 409)
        ok = self.c.post('/api/help/diagram/save', json={'name': 'board', 'data': self.data, 'svg': '<svg>2</svg>', 'mtime': d['mtime']})
        self.assertEqual(ok.status_code, 200)
        r = self.c.get('/help/file/diagrams/board.svg')
        self.assertEqual(r.get_data(as_text=True), '<svg>2</svg>')
        r.close()

        r = self.c.post('/api/help/diagram/rename', json={'name': 'board', 'new_name': 'board2'}).get_json()
        self.assertEqual(r, {'name': 'board2', 'docs': ['hw/page.md']})
        self.assertIn('../diagrams/board2.svg', help_docs.read_doc('hw/page.md')['content'])

        self.assertEqual(self.c.post('/api/help/diagram/delete', json={'name': 'board2'}).status_code, 200)
        self.assertEqual(self.c.get('/api/help/diagram?name=board2').status_code, 404)
        self.assertEqual(len(os.listdir(os.path.join(help_docs.root(), '.trash'))), 2)   # json + svg

    def test_page_has_editor(self):
        html = self.c.get('/help').get_data(as_text=True)
        for needle in ['id="dg-pane"', 'diagram_render.js', 'diagrams.js', 'dg-pins-overlay']:
            self.assertIn(needle, html)
        self.assertEqual(self.c.get('/diagrams').status_code, 404)                     # only inside Docs
