"""Raw data terminal of the HW Utils popup (core/ttyterm.py): serial port / TCP client / UDP socket, polled output,
send, DTR / RTS, profiles per host in config.json (``tty``). Login only; serial is locked while a test script runs."""
import base64

from flask import Blueprint, jsonify, request

from core import config, modbus, ttyterm
from core.auth import login_required
from core.test_runner import runner
from core.ttyterm import TtyError

bp = Blueprint('ttyterm', __name__)

ttyterm.blocked = lambda: 'A test script is running — serial ports are locked' if runner.is_running() else None


@bp.errorhandler(TtyError)
def _error(e):
    return jsonify({'error': str(e)}), e.status


def _body():
    return request.get_json(silent=True, force=True) or {}


@bp.route('/api/tty/info')
@login_required
def api_info():
    saved = config.get('tty') or {}
    try:
        profiles = ttyterm.check_profiles(saved) if saved.get('profiles') else {'profiles': [], 'current': ''}
    except TtyError:
        profiles = {'profiles': [], 'current': ''}
    return jsonify({'ports': modbus.ports(), 'bauds': modbus.BAUDS, 'sessions': ttyterm.sessions(),
                    'blocked': ttyterm.blocked(), **profiles})


@bp.route('/api/tty/open', methods=['POST'])
@login_required
def api_open():
    return jsonify(ttyterm.open_session(_body().get('conn')))


@bp.route('/api/tty/read')
@login_required
def api_read():
    return jsonify(ttyterm.get(request.args.get('id')).read(request.args.get('since', 0, type=int)))


@bp.route('/api/tty/send', methods=['POST'])
@login_required
def api_send():
    d = _body()
    s = ttyterm.get(d.get('id'))
    if 'b64' in d:
        try:
            data = base64.b64decode(d.get('b64') or '', validate=True)
        except ValueError:
            raise TtyError('Bad data')
    else:
        data = ttyterm.decode_payload(str(d.get('text') or ''), bool(d.get('hex')))
    return jsonify(s.send(data))


@bp.route('/api/tty/oneshot', methods=['POST'])
@login_required
def api_oneshot():
    d = _body()
    data = ttyterm.decode_payload(str(d.get('text') or ''), bool(d.get('hex')))
    if not data:
        raise TtyError('Nothing to send')
    return jsonify(ttyterm.oneshot(d.get('conn'), data, d.get('wait', True) is not False, d.get('timeout', 1000)))


@bp.route('/api/tty/sessions')
@login_required
def api_sessions():
    return jsonify({'sessions': ttyterm.list_sessions()})


@bp.route('/api/tty/session')
@login_required
def api_session():
    return jsonify(ttyterm.load_session(request.args.get('name', '')))


@bp.route('/api/tty/session/save', methods=['POST'])
@login_required
def api_session_save():
    d = _body()
    return jsonify(ttyterm.save_session(d.get('name', ''), d.get('data'), bool(d.get('overwrite'))))


@bp.route('/api/tty/session/delete', methods=['POST'])
@login_required
def api_session_delete():
    return jsonify(ttyterm.delete_session(_body().get('name', '')))


@bp.route('/api/tty/lines', methods=['POST'])
@login_required
def api_lines():
    d = _body()
    return jsonify(ttyterm.get(d.get('id')).set_lines(d.get('dtr'), d.get('rts')))


@bp.route('/api/tty/close', methods=['POST'])
@login_required
def api_close():
    return jsonify(ttyterm.close(_body().get('id')))


@bp.route('/api/tty/profiles', methods=['POST'])
@login_required
def api_profiles():
    data = ttyterm.check_profiles(_body())
    config.save_key('tty', data)
    return jsonify(data)
