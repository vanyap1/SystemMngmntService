"""Diagram store: pinout / block diagrams in help_dir/diagrams, edited on the Docs page (static/js/diagrams.js).

Every diagram is ``<name>.json`` (the editable model, see static/js/diagram_render.js) plus ``<name>.svg``
exported by the editor on every save, so documentation pages embed ``../diagrams/<name>.svg``.
Deleted diagrams are moved to help_dir/.trash.

A diagram with a ``unit`` item marked ``master`` is a library component (DUT, instrument, mux, relay, jig…);
other diagrams place it as ``{"type": "unit", "ref": "<name>", …}`` with a copy of its ports, so ``ref`` links
are kept in sync on rename and reported by ``used_in()``.

Catalogs (sidebar groups, the files stay flat): ``station`` (a whole test station), ``assembly`` (a jig / board
built of units), ``bus`` (bus-level module: one port per interface), ``uut`` (products under test: a DUT symbol),
``component`` (instrument, mux, relay… = a symbol only) and ``diagram`` (pinouts, block diagrams).
``data["catalog"]`` sets it explicitly, otherwise ``catalog()`` derives it from the content.
"""
import json
import os
import re

from core import help_docs
from core.help_docs import DocError

DIR = 'diagrams'
MAX_JSON = 4 * 1024 * 1024
MAX_SVG = 8 * 1024 * 1024
_NAME = re.compile(r'^[\w][\w.-]{0,79}$')


def folder():
    return os.path.join(help_docs.root(), DIR)


def check_name(name):
    name = (name or '').strip()
    if name.lower().endswith('.json'):
        name = name[:-5]
    if not _NAME.match(name) or name.endswith('.'):
        raise DocError(f'Invalid diagram name: "{name}" (letters, digits, . _ -)')
    return name


def _paths(name):
    base = os.path.join(folder(), name)
    return base + '.json', base + '.svg'


def _existing(name):
    name = check_name(name)
    js, svg = _paths(name)
    if not os.path.isfile(js):
        raise DocError('Diagram not found', 404)
    return name, js, svg


def _master(data):
    for it in (data.get('items') or []) if isinstance(data, dict) else []:
        if isinstance(it, dict) and it.get('type') == 'unit' and it.get('master'):
            return it
    return None


def _component(data):
    m = _master(data)
    if m is None:
        return None
    return {'category': str(m.get('category') or 'custom'), 'title': str(m.get('title') or ''),
            'ports': len(m.get('ports') or []), 'detail': 'bus' if m.get('detail') == 'bus' else 'pins'}


CATALOGS = ('station', 'assembly', 'bus', 'component', 'uut', 'diagram')


def catalog(data):
    """Catalog of a diagram model (keep in sync with DiagramRender.catalogOf)."""
    if not isinstance(data, dict):
        return 'diagram'
    if data.get('catalog') in CATALOGS:
        return data['catalog']
    units = [it for it in data.get('items') or []
             if isinstance(it, dict) and it.get('type') == 'unit' and not it.get('master')]
    m = _master(data)
    if m is not None:
        if m.get('category') == 'station':
            return 'station'
        if m.get('category') == 'dut':
            return 'uut'
        if units or m.get('category') == 'jig':
            return 'assembly'
        return 'bus' if m.get('detail') == 'bus' else 'component'
    return 'station' if units else 'diagram'


def _load_all():
    """(name, path, data) of every readable diagram."""
    if not os.path.isdir(folder()):
        return
    for e in os.scandir(folder()):
        if not e.is_file() or not e.name.endswith('.json') or e.name.startswith('.'):
            continue
        try:
            with open(e.path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            yield e.name[:-5], e.path, data


def _refs(data):
    return [it for it in data.get('items') or [] if isinstance(it, dict) and it.get('type') == 'unit' and it.get('ref')]


def used_in(name):
    """Diagrams that place ``name`` as a unit."""
    return sorted(n for n, _, data in _load_all() if n != name and any(it['ref'] == name for it in _refs(data)))


def list_diagrams():
    if not os.path.isdir(folder()):
        return []
    items = []
    for e in sorted(os.scandir(folder()), key=lambda e: e.name.lower()):
        if not e.is_file() or not e.name.endswith('.json') or e.name.startswith('.'):
            continue
        name = e.name[:-5]
        title, component, cat = name, None, 'diagram'
        try:
            with open(e.path, encoding='utf-8') as f:
                data = json.load(f)
            title = (data.get('title') or name).strip()
            component = _component(data)
            cat = catalog(data)
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        svg = os.path.join(folder(), name + '.svg')
        items.append({'name': name, 'title': title, 'mtime': e.stat().st_mtime, 'size': e.stat().st_size,
                      'svg': os.path.isfile(svg), 'component': component, 'catalog': cat})
    return items


def read(name):
    name, js, _ = _existing(name)
    with open(js, encoding='utf-8') as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise DocError(f'Broken diagram file: {e}', 500)
    return {'name': name, 'data': data, 'mtime': os.path.getmtime(js)}


def _check(data, svg):
    if not isinstance(data, dict) or not isinstance(data.get('items', []), list):
        raise DocError('Bad diagram data')
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if len(text.encode('utf-8')) > MAX_JSON:
        raise DocError('Diagram too large')
    if svg is not None:
        if not isinstance(svg, str) or not svg.lstrip().startswith('<svg') or len(svg.encode('utf-8')) > MAX_SVG:
            raise DocError('Bad SVG')
    return text


def create(name, data, svg=None):
    name = check_name(name)
    js, svg_path = _paths(name)
    if os.path.exists(js):
        raise DocError('Already exists', 409)
    text = _check(data, svg)
    help_docs._write_text(js, text)
    if svg:
        help_docs._write_text(svg_path, svg)
    return {'name': name, 'mtime': os.path.getmtime(js)}


def save(name, data, svg=None, base_mtime=None, force=False):
    """Write the model and its SVG export; ``base_mtime`` older than the file on disk = conflict (409)."""
    name, js, svg_path = _existing(name)
    text = _check(data, svg)
    if not force and base_mtime is not None:
        try:
            if abs(os.path.getmtime(js) - float(base_mtime)) > 0.001:
                raise DocError('The diagram was changed by someone else', 409)
        except (TypeError, ValueError):
            pass
    help_docs._write_text(js, text)
    if svg:
        help_docs._write_text(svg_path, svg)
    return {'name': name, 'mtime': os.path.getmtime(js)}


def _relink_docs(old, new):
    """Point documentation links from diagrams/<old>.svg to diagrams/<new>.svg."""
    pat = re.compile(r'(\bdiagrams/)' + re.escape(old) + r'(\.svg)')
    changed = []
    for d in help_docs.list_docs():
        full = os.path.join(help_docs.root(), *d['path'].split('/'))
        with open(full, encoding='utf-8', errors='replace') as f:
            text = f.read()
        fixed = pat.sub(lambda m: m.group(1) + new + m.group(2), text)
        if fixed != text:
            help_docs._write_text(full, fixed)
            changed.append(d['path'])
    return changed


def _relink_units(old, new):
    """Point units placed from library component ``old`` to ``new``; returns the changed diagram names."""
    changed = []
    for n, path, data in list(_load_all()):
        units = [it for it in _refs(data) if it['ref'] == old]
        if not units:
            continue
        for it in units:
            it['ref'] = new
        help_docs._write_text(path, json.dumps(data, ensure_ascii=False, indent=1))
        changed.append(n)
    return sorted(changed)


def rename(name, new_name):
    name, js, svg = _existing(name)
    new_name = check_name(new_name)
    if new_name == name:
        return {'name': name, 'docs': []}
    new_js, new_svg = _paths(new_name)
    if os.path.exists(new_js):
        raise DocError('Already exists', 409)
    os.replace(js, new_js)
    if os.path.isfile(svg):
        os.replace(svg, new_svg)
    return {'name': new_name, 'docs': _relink_docs(name, new_name), 'diagrams': _relink_units(name, new_name)}


def delete(name):
    name, js, svg = _existing(name)
    help_docs._to_trash(js, f'{DIR}/{name}.json')
    if os.path.isfile(svg):
        help_docs._to_trash(svg, f'{DIR}/{name}.svg')
    return {'name': name}


def used_by(name):
    """Documentation pages that embed or link this diagram."""
    needle = f'{DIR}/{name}.svg'
    pages = []
    for d in help_docs.list_docs():
        full = os.path.join(help_docs.root(), *d['path'].split('/'))
        try:
            with open(full, encoding='utf-8', errors='replace') as f:
                if needle in f.read():
                    pages.append(d['path'])
        except OSError:
            pass
    return pages
