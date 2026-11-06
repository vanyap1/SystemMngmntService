"""Update of the panel itself from its git upstream: status for the top bar button, pull, self-restart. Login only."""
from flask import Blueprint, jsonify, request

from core import updates
from core.auth import login_required
from core.git_ops import GitError

bp = Blueprint('updates', __name__)


@bp.errorhandler(GitError)
def _git_error(e):
    return jsonify({'error': str(e), 'output': e.output}), e.status


@bp.route('/api/update/status')
@login_required
def api_status():
    return jsonify(updates.status(force=request.args.get('force') == '1'))


@bp.route('/api/update/apply', methods=['POST'])
@login_required
def api_apply():
    res = updates.apply()
    return jsonify({'ok': True, **res, 'status': updates.status()})


@bp.route('/api/update/restart', methods=['POST'])
@login_required
def api_restart():
    unit = updates.restart()
    return jsonify({'ok': True, 'message': f'Restarting {unit}…'})
