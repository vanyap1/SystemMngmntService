"""Test log viewer: browse, filter and analyse testLogs/*.log of the test platform."""
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request

from core import config, test_logs
from core.auth import login_required
from core.test_runner import LOG_PATTERN, list_scripts

bp = Blueprint('logs', __name__)
PAGE_MAX = 500


def _filtered():
    a = request.args
    return test_logs.query(script=a.get('script', ''), verdict=a.get('verdict', ''), q=a.get('q', ''),
                           date_from=a.get('from', ''), date_to=a.get('to', ''), step=a.get('step', ''))


@bp.route('/logs')
@login_required
def logs():
    return render_template('logs.html', logs_dir=config.test_logs_dir())


@bp.route('/api/logs')
@login_required
def api_logs():
    """Filtered log list (newest first), one page of rows plus statistics over all matches."""
    logs = _filtered()
    try:
        offset = max(0, int(request.args.get('offset', 0)))
        limit = min(PAGE_MAX, max(1, int(request.args.get('limit', 100))))
    except ValueError:
        return jsonify({'error': 'Bad offset/limit'}), 400
    scripts = sorted({s['name'] for s in list_scripts()} |
                     {LOG_PATTERN.match(n).group(2) + '.py' for n in test_logs.all_names()})
    return jsonify({'total': len(logs), 'offset': offset,
                    'items': [test_logs.list_item(l) for l in logs[offset:offset + limit]],
                    'summary': test_logs.summary(logs), 'scripts': scripts})


@bp.route('/api/logs/view/<name>')
@login_required
def api_view(name):
    log = test_logs.parse(name)
    if not log:
        return jsonify({'error': 'Log not found'}), 404
    return jsonify(log)


@bp.route('/api/logs/step')
@login_required
def api_step():
    """One step across the filtered logs: every value and its statistics (Cpk when it has limits)."""
    step = request.args.get('name', '')
    if not step:
        return jsonify({'error': 'Step name required'}), 400
    a = request.args
    logs = test_logs.query(script=a.get('script', ''), verdict=a.get('verdict', ''), q=a.get('q', ''),
                           date_from=a.get('from', ''), date_to=a.get('to', ''))
    return jsonify(test_logs.step_values(logs, step))


@bp.route('/api/logs/export.csv')
@login_required
def api_export():
    name = f"test_logs_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return Response(test_logs.to_csv(_filtered()), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})
