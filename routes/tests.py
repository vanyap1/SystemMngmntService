"""Test platform page: run test scripts, watch results live, browse run logs."""
import os

from flask import Blueprint, jsonify, render_template, request, send_file

from core import config, test_runner
from core.auth import login_required
from core.gpio_ctl import gpio_ctl
from core.shell import resolve_inside

bp = Blueprint('tests', __name__)
runner = test_runner.runner


@bp.route('/tests')
@login_required
def tests():
    return render_template('tests.html', tests_dir=config.tests_dir(),
                           logs_dir=config.test_logs_dir())


@bp.route('/api/tests/scripts')
@login_required
def api_scripts():
    return jsonify({'scripts': test_runner.list_scripts()})


@bp.route('/api/tests/start', methods=['POST'])
@login_required
def api_start():
    data = request.get_json(silent=True) or {}
    if not runner.is_running():
        gpio_ctl.release_all()      # the script needs the fixture lines
    try:
        run = runner.start(data.get('script', ''), data.get('serial', ''),
                           data.get('stop_on_fail', True))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 409
    return jsonify({'success': True, 'run_id': run.id})


@bp.route('/api/tests/stop', methods=['POST'])
@login_required
def api_stop():
    if not runner.stop():
        return jsonify({'error': 'No test is running'}), 409
    return jsonify({'success': True})


@bp.route('/api/tests/answer', methods=['POST'])
@login_required
def api_answer():
    """Operator answer to the pending prompt of the running script."""
    data = request.get_json(silent=True) or {}
    try:
        value = runner.answer(data.get('run_id'), data.get('prompt_id'), data.get('value'))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 409
    return jsonify({'success': True, 'value': value})


@bp.route('/api/tests/status')
@login_required
def api_status():
    """Incremental status: pass back run_id and the counts already received."""
    return jsonify(runner.status(request.args.get('run_id', type=int),
                                 request.args.get('results_from', 0, type=int),
                                 request.args.get('output_from', 0, type=int)))


@bp.route('/api/tests/logs')
@login_required
def api_logs():
    return jsonify({'logs': test_runner.list_logs()})


def _log_path(name):
    if not test_runner.LOG_PATTERN.match(name or ''):
        return None
    path = resolve_inside(os.path.join(config.test_logs_dir(), name), config.test_logs_dir())
    return path if path and os.path.isfile(path) else None


@bp.route('/api/tests/stats')
@login_required
def api_stats():
    return jsonify(test_runner.board_stats(request.args.get('script', '')))


@bp.route('/api/tests/logs/delete', methods=['POST'])
@login_required
def api_delete_logs():
    """Delete one log ({"name": ...}) or all logs ({"all": true})."""
    data = request.get_json(silent=True) or {}
    if data.get('all'):
        deleted = test_runner.delete_logs()
    elif _log_path(data.get('name')):
        deleted = test_runner.delete_logs(data['name'])
    else:
        return jsonify({'error': 'Log not found'}), 404
    return jsonify({'success': True, 'deleted': deleted})


@bp.route('/api/tests/logs/<name>')
@login_required
def api_log(name):
    path = _log_path(name)
    if not path:
        return jsonify({'error': 'Log not found'}), 404
    if request.args.get('download'):
        return send_file(path, as_attachment=True)
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read(), 200, {'Content-Type': 'text/plain; charset=utf-8'}
