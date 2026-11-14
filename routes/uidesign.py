"""Visual UI designer (page UI, between Code and Docs): screens for the device display in UI/screens/. Login only."""
from flask import Blueprint, abort, jsonify, render_template, request, send_file

from core import display_ui, ui_screens
from core.auth import login_required

bp = Blueprint('uidesign', __name__)


@bp.errorhandler(ui_screens.ScreenError)
def _error(e):
    return jsonify({'error': str(e)}), e.status


@bp.errorhandler(display_ui.DisplayError)
def _display_error(e):
    return jsonify({'error': str(e)}), e.status


@bp.route('/ui')
@login_required
def page():
    return render_template('uidesign.html')


@bp.route('/api/uiscreens')
@login_required
def api_list():
    """Screens, pictures for image widgets, the display settings (size, background) and the editor metadata."""
    st = display_ui.supervisor.status()
    return jsonify({'screens': ui_screens.list_screens(), 'images': ui_screens.images(), 'meta': ui_screens.meta(),
                    'display': {'settings': st['settings'], 'state': st['state'], 'script': st['script'],
                                'screen': (st['gpu'].get('outputs') or [{}])[0] if st.get('gpu') else {}}})


@bp.route('/api/uiscreens/<name>')
@login_required
def api_get(name):
    return jsonify({'name': name, 'screen': ui_screens.load(name)})


@bp.route('/api/uiscreens/<name>', methods=['POST'])
@login_required
def api_save(name):
    clean = ui_screens.save(name, request.get_json(silent=True) or {})
    return jsonify({'ok': True, 'name': name, 'screen': clean, 'screens': ui_screens.list_screens()})


@bp.route('/api/uiscreens/<name>/delete', methods=['POST'])
@login_required
def api_delete(name):
    ui_screens.delete(name)
    return jsonify({'ok': True, 'screens': ui_screens.list_screens()})


@bp.route('/api/uiscreens/<name>/show', methods=['POST'])
@login_required
def api_show(name):
    """Show this screen on the device (Settings → Display: script = screens/<name>.json, enabled)."""
    ui_screens.load(name)
    s = display_ui.save(dict(display_ui.settings(), enabled=True, script=f'screens/{name}.json'))
    return jsonify({'ok': True, 'settings': s})


@bp.route('/api/uiscreens/image/<name>')
@login_required
def api_image(name):
    path = ui_screens.image_path(name)
    if not path:
        abort(404)
    return send_file(path, max_age=3600)
