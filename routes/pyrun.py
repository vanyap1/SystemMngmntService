"""Run / debug Python scripts from the code editor (core/pyrun.py, core/pydbg_agent.py). Login only.
Scripts must be .py files inside target_dir; one session at a time, kept alive by polling."""
import time

from flask import Blueprint, jsonify, request

from core import net, pyrun
from core.gpio_ctl import gpio_ctl
from core.auth import login_required
from core.pyrun import RunError
from core.test_runner import runner

bp = Blueprint('pyrun', __name__)

pyrun.blocked = lambda: 'A test script is running on the Tests page — stop it first' if runner.is_running() else None


def _before_start():
    gpio_ctl.release_all()      # the script may need the fixture lines held by the GPIO popup
    net.stop_all_cyclic()


pyrun.before_start = _before_start

ACTIONS = ('continue', 'next', 'step', 'return', 'pause')


@bp.errorhandler(RunError)
def _run_error(e):
    return jsonify({'error': str(e)}), e.status


def _body():
    return request.get_json(silent=True) or {}


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@bp.route('/api/pyrun/start', methods=['POST'])
@login_required
def api_start():
    d = _body()
    s = pyrun.start(d.get('path'), d.get('args') or [], d.get('debug') is True, d.get('breaks') or {},
                    d.get('stop_on_entry') is True)
    return jsonify(s.snapshot(0))


@bp.route('/api/pyrun/poll')
@login_required
def api_poll():
    s = pyrun.current()
    if not s:
        return jsonify({'state': 'none'})
    if request.args.get('id') and str(s.id) == request.args.get('id'):
        s.last_poll = time.time()
    return jsonify(s.snapshot(_int(request.args.get('since'))))


@bp.route('/api/pyrun/cmd', methods=['POST'])
@login_required
def api_cmd():
    d = _body()
    s = pyrun.get(d.get('id'))
    action = d.get('action')
    if action == 'jump':                         # run a line again / set the next line (nothing is undone)
        if s.state != 'paused':
            raise RunError('The program is not paused', 409)
        line = d.get('line')
        if line is not None and (not isinstance(line, int) or line < 1):
            raise RunError('Bad line')
        r = s.request({'cmd': 'jump', 'line': line})
        if r.get('error'):
            raise RunError(r['error'], 409)
        return jsonify({'ok': True, 'state': s.state, 'line': r.get('line')})
    if action == 'frame':
        if s.state != 'paused':
            raise RunError('The program is not paused', 409)
        s._send({'cmd': 'frame', 'frame': _int(d.get('frame'))})
    elif action in ACTIONS:
        s.command(action)
    else:
        raise RunError('Unknown action')
    return jsonify({'ok': True, 'state': s.state})


@bp.route('/api/pyrun/input', methods=['POST'])
@login_required
def api_input():
    d = _body()
    text = d.get('text')
    if not isinstance(text, str) or len(text) > 4096:
        raise RunError('Bad input')
    pyrun.get(d.get('id')).write(text)
    return jsonify({'ok': True})


@bp.route('/api/pyrun/stop', methods=['POST'])
@login_required
def api_stop():
    d = request.get_json(silent=True, force=True) or {}      # also sent by navigator.sendBeacon
    s = pyrun.current()
    if s and (d.get('id') is None or str(d.get('id')) == str(s.id)):
        s.stop()
    return jsonify({'ok': True})


def _paused(d):
    s = pyrun.get(d.get('id'))
    if s.state != 'paused':
        raise RunError('The program is not paused', 409)
    return s


@bp.route('/api/pyrun/eval', methods=['POST'])
@login_required
def api_eval():
    d = _body()
    expr = d.get('expr')
    if not isinstance(expr, str) or not expr.strip() or len(expr) > 500:
        raise RunError('Bad expression')
    r = _paused(d).request({'cmd': 'eval', 'expr': expr, 'frame': _int(d.get('frame'), -1), 'hover': d.get('hover') is True})
    if r.get('error'):
        return jsonify({'error': r['error']}), 200 if d.get('hover') else 400
    return jsonify(r['result'])


@bp.route('/api/pyrun/vars', methods=['POST'])
@login_required
def api_vars():
    d = _body()
    expr = d.get('expr')
    if expr is not None and (not isinstance(expr, str) or len(expr) > 500):
        raise RunError('Bad expression')
    r = _paused(d).request({'cmd': 'vars', 'expr': expr, 'frame': _int(d.get('frame'), -1)})
    if r.get('error'):
        raise RunError(r['error'])
    return jsonify({'vars': r['vars']})


@bp.route('/api/pyrun/breaks', methods=['POST'])
@login_required
def api_breaks():
    return jsonify({'breaks': pyrun.set_breaks(_body().get('breaks') or {})})
