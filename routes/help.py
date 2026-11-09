"""Documentation: Markdown viewer/editor for help_dir (pages, img/ images, docs/ attachments) and the diagram
editor (help_dir/diagrams). Login only."""
import json
import mimetypes

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from core import diagrams, help_docs
from core.auth import login_required
from core.help_docs import DocError

bp = Blueprint('help', __name__)

# Served help files may be HTML/SVG written by users: never let them run scripts in the panel's origin.
_RAW_HEADERS = {'Content-Security-Policy': "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
                'X-Content-Type-Options': 'nosniff'}


def _err(e):
    return jsonify({'error': str(e)}), e.status


@bp.errorhandler(DocError)
def _doc_error(e):
    return _err(e)


@bp.route('/help')
@login_required
def help_page():
    return render_template('help.html', help_dir=help_docs.root())


@bp.route('/help/file/<path:rel>')
@login_required
def help_file(rel):
    """Images, attachments and raw pages; ``?dl=1`` forces a download."""
    full = help_docs.file_path(rel)
    if not full:
        return 'Not found', 404
    mime = mimetypes.guess_type(full)[0] or 'application/octet-stream'
    if rel.lower().endswith('.md'):
        mime = 'text/plain; charset=utf-8'
    resp = send_file(full, mimetype=mime, as_attachment=request.args.get('dl') == '1',
                     download_name=rel.rsplit('/', 1)[-1], max_age=0)
    resp.headers.update(_RAW_HEADERS)
    return resp


@bp.route('/api/help/tree')
@login_required
def api_tree():
    return jsonify({'docs': help_docs.list_docs(), 'root': help_docs.root(),
                    'reserved': sorted(help_docs.RESERVED)})


@bp.route('/api/help/doc')
@login_required
def api_doc():
    return jsonify(help_docs.read_doc(request.args.get('path', '')))


@bp.route('/api/help/doc', methods=['POST'])
@login_required
def api_save():
    d = request.get_json(silent=True) or {}
    return jsonify(help_docs.save_doc(d.get('path', ''), d.get('content'), d.get('mtime'), bool(d.get('force'))))


@bp.route('/api/help/create', methods=['POST'])
@login_required
def api_create():
    d = request.get_json(silent=True) or {}
    return jsonify(help_docs.create_doc(d.get('path', ''), d.get('title', '')))


@bp.route('/api/help/rename', methods=['POST'])
@login_required
def api_rename():
    d = request.get_json(silent=True) or {}
    return jsonify(help_docs.rename_doc(d.get('path', ''), d.get('new_path', '')))


@bp.route('/api/help/delete', methods=['POST'])
@login_required
def api_delete():
    d = request.get_json(silent=True) or {}
    return jsonify(help_docs.delete_doc(d.get('path', '')))


@bp.route('/api/help/search')
@login_required
def api_search():
    return jsonify({'results': help_docs.search(request.args.get('q', ''))})


@bp.route('/api/help/assets')
@login_required
def api_assets():
    return jsonify({'items': help_docs.list_assets(request.args.get('kind', ''))})


@bp.route('/api/help/upload', methods=['POST'])
@login_required
def api_upload():
    """Multipart upload: ``kind`` = img|docs, one or more ``file`` fields."""
    kind = request.form.get('kind', '')
    files = request.files.getlist('file')
    if not files:
        return jsonify({'error': 'No file'}), 400
    return jsonify({'kind': kind, 'names': [help_docs.save_upload(kind, f) for f in files]})


@bp.route('/api/help/asset_delete', methods=['POST'])
@login_required
def api_asset_delete():
    d = request.get_json(silent=True) or {}
    return jsonify(help_docs.delete_asset(d.get('kind', ''), d.get('name', '')))


# ── Diagrams (pinouts, block diagrams) — edited inside the Docs page ──

@bp.route('/api/help/diagrams')
@login_required
def api_diagrams():
    return jsonify({'items': diagrams.list_diagrams()})


@bp.route('/api/help/diagram')
@login_required
def api_diagram():
    d = diagrams.read(request.args.get('name', ''))
    d['used_by'] = diagrams.used_by(d['name'])
    d['used_in'] = diagrams.used_in(d['name'])
    # not jsonify: it sorts keys, and the order of pin kinds is the legend order
    return Response(json.dumps(d, ensure_ascii=False), mimetype='application/json')


@bp.route('/api/help/diagram/create', methods=['POST'])
@login_required
def api_diagram_create():
    d = request.get_json(silent=True) or {}
    return jsonify(diagrams.create(d.get('name', ''), d.get('data') or {'items': []}, d.get('svg')))


@bp.route('/api/help/diagram/save', methods=['POST'])
@login_required
def api_diagram_save():
    d = request.get_json(silent=True) or {}
    return jsonify(diagrams.save(d.get('name', ''), d.get('data'), d.get('svg'), d.get('mtime'), bool(d.get('force'))))


@bp.route('/api/help/diagram/rename', methods=['POST'])
@login_required
def api_diagram_rename():
    d = request.get_json(silent=True) or {}
    return jsonify(diagrams.rename(d.get('name', ''), d.get('new_name', '')))


@bp.route('/api/help/diagram/delete', methods=['POST'])
@login_required
def api_diagram_delete():
    d = request.get_json(silent=True) or {}
    return jsonify(diagrams.delete(d.get('name', '')))
