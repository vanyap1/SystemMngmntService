"""Device display (Settings → Display): status, scripts, settings, restart of the Kivy UI process. Login only."""
from flask import Blueprint, abort, jsonify, request, send_file

from core import display_ui
from core.auth import login_required

bp = Blueprint('display', __name__)


@bp.errorhandler(display_ui.DisplayError)
def _error(e):
    return jsonify({'error': str(e)}), e.status


@bp.route('/api/display/status')
@login_required
def api_status():
    return jsonify(display_ui.supervisor.status())


@bp.route('/api/display/scripts')
@login_required
def api_scripts():
    return jsonify({'scripts': display_ui.scripts(), 'modes': display_ui.MODES, 'rotations': display_ui.ROTATIONS,
                    'cursors': display_ui.CURSORS})


@bp.route('/api/display/backgrounds')
@login_required
def api_backgrounds():
    return jsonify({'backgrounds': display_ui.backgrounds()})


@bp.route('/api/display/background/<name>')
@login_required
def api_background(name):
    """A picture of UI/backgrounds/ (preview on Settings → Display)."""
    path = display_ui.background_path(name)
    if not path:
        abort(404)
    return send_file(path, max_age=3600)


@bp.route('/api/display/settings', methods=['POST'])
@login_required
def api_settings():
    """Save the settings; the supervisor applies them at once (replace / stop the running script)."""
    s = display_ui.save(request.get_json(silent=True) or {})
    return jsonify({'ok': True, 'settings': s, 'status': display_ui.supervisor.status()})


@bp.route('/api/display/restart', methods=['POST'])
@login_required
def api_restart():
    display_ui.supervisor.restart()
    return jsonify({'ok': True, 'status': display_ui.supervisor.status()})
