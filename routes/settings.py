"""Settings page: edits this host's section of config.json."""
from flask import Blueprint, jsonify, render_template, request

from core import config
from core.auth import login_required

bp = Blueprint('settings', __name__)


@bp.route('/settings')
@login_required
def settings():
    return render_template('settings.html', cfg=config.CFG,
                           hostname=config.HOSTNAME,
                           has_host_config=config.host_section() is not None,
                           service_actions=config.SERVICE_ACTIONS,
                           public_actions=config.public_service_actions())


@bp.route('/api/settings', methods=['POST'])
@login_required
def save():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data'}), 400
    try:
        config.update(data)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/settings/reset', methods=['POST'])
@login_required
def reset():
    """Forget this host's settings and fall back to the defaults."""
    try:
        config.reset_host()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
