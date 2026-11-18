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


@bp.route('/api/update/plan', methods=['POST'])
@login_required
def api_plan():
    """Fetch and list what a forced update would replace (Git panel → Update panel)."""
    return jsonify(updates.plan())


@bp.route('/api/update/force', methods=['POST'])
@login_required
def api_force():
    """Update the panel to its upstream whatever is local (saved first), keep config.json, restart the unit.
    {confirm: true} is required when plan() reported issues."""
    d = request.get_json(silent=True) or {}
    try:
        res = updates.force_update(bool(d.get('confirm')))
    except updates.UpdateBlocked as e:
        return jsonify({'error': str(e), 'plan': e.plan}), 409
    return jsonify({'ok': True, **res})


@bp.route('/api/update/job', methods=['GET', 'POST'])
@login_required
def api_job():
    """GET: progress of the update job. POST {confirm}: start the forced update in the background (no restart —
    the UI offers it when the job is done, /api/update/restart)."""
    if request.method == 'POST':
        d = request.get_json(silent=True) or {}
        return jsonify(updates.start_job(bool(d.get('confirm'))))
    return jsonify(updates.job_status())
