"""Interactive terminal (core/terminal.py): a shell in a pty streamed to xterm.js. Login only."""
from flask import Blueprint, Response, jsonify, request, stream_with_context

from core import terminal
from core.auth import login_required
from core.terminal import TermError

bp = Blueprint('terminal', __name__)


@bp.errorhandler(TermError)
def _term_error(e):
    return jsonify({'error': str(e)}), e.status


def _body():
    return request.get_json(silent=True, force=True) or {}


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@bp.route('/api/term/open', methods=['POST'])
@login_required
def api_open():
    """{cols, rows, id?} -> reattach to id (if alive) or start a shell: {id, user, offset, start, reattached}."""
    d = _body()
    s, again = terminal.open_session(_int(d.get('cols'), 120), _int(d.get('rows'), 30), d.get('id'))
    return jsonify({**s.info(), 'reattached': again})


@bp.route('/api/term/stream')
@login_required
def api_stream():
    """Server-Sent Events with the output after byte ?from= (0 = everything still buffered)."""
    s = terminal.get(request.args.get('id'))
    offset = max(0, _int(request.args.get('from'), 0))
    resp = Response(stream_with_context(terminal.stream(s, offset)), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


@bp.route('/api/term/input', methods=['POST'])
@login_required
def api_input():
    d = _body()
    data = d.get('data')
    if not isinstance(data, str) or len(data) > 65536:
        raise TermError('Bad input')
    terminal.get(d.get('id')).write(data)
    return jsonify({'ok': True})


@bp.route('/api/term/resize', methods=['POST'])
@login_required
def api_resize():
    d = _body()
    terminal.get(d.get('id')).resize(_int(d.get('cols'), 120), _int(d.get('rows'), 30))
    return jsonify({'ok': True})


@bp.route('/api/term/close', methods=['POST'])
@login_required
def api_close():
    """Also sent by navigator.sendBeacon when the page is closed."""
    return jsonify({'ok': terminal.close(_body().get('id'))})
