"""Network interfaces overview and the SocketCAN tool (Devices popup, "Network" tab)."""
from flask import Blueprint, jsonify, request

from core import net
from core.auth import login_required
from core.test_runner import runner

bp = Blueprint('net', __name__)


def _error(e, status=400):
    return jsonify({'error': str(e)}), status


@bp.route('/api/net/interfaces')
@login_required
def api_interfaces():
    return jsonify({'interfaces': net.interfaces(), **net.routes(), 'bitrates': net.BITRATES})


@bp.route('/api/net/can/link', methods=['POST'])
@login_required
def api_can_link():
    """{iface, action: open|close, bitrate, sample_point, restart_ms, listen_only}"""
    data = request.get_json(silent=True) or {}
    if runner.is_running():
        return _error('A test script is running — CAN configuration is locked', 409)
    iface, action = data.get('iface'), data.get('action')
    try:
        if action == 'close':
            net.can_set_up(iface, False)
        elif action == 'open':
            if data.get('bitrate'):
                net.can_configure(iface, data['bitrate'], data.get('sample_point'),
                                  data.get('restart_ms'), bool(data.get('listen_only')))
            else:
                net.can_set_up(iface, True)     # vcan or keep the current bit timing
        else:
            return _error('Unknown action')
    except net.NetError as e:
        return _error(e, 500)
    return jsonify({'success': True})


@bp.route('/api/net/can/frames')
@login_required
def api_can_frames():
    """Frames since ``since``; polling keeps the CAN socket open (lease)."""
    try:
        since = int(request.args.get('since', 0))
        return jsonify(net.can_bus(request.args.get('iface')).frames(since))
    except ValueError:
        return _error('since must be a number')
    except net.NetError as e:
        return _error(e)


@bp.route('/api/net/can/send', methods=['POST'])
@login_required
def api_can_send():
    """{iface, action: send|cyclic|stop|stop_all|clear, id, ext, rtr, data, period_ms, job}"""
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'send')
    try:
        bus = net.can_bus(data.get('iface'))
        if action == 'send':
            bus.send(data.get('id'), data.get('ext'), data.get('rtr'), data.get('data'))
        elif action == 'cyclic':
            return jsonify({'success': True, 'job': bus.start_cyclic(
                data.get('id'), data.get('ext'), data.get('rtr'), data.get('data'), data.get('period_ms'))})
        elif action == 'stop':
            bus.stop_cyclic(int(data.get('job', -1)))
        elif action == 'stop_all':
            bus.stop_cyclic()
        elif action == 'clear':
            bus.clear()
        else:
            return _error('Unknown action')
    except (net.NetError, ValueError) as e:
        return _error(e, 409 if isinstance(e, net.NetError) else 400)
    return jsonify({'success': True})
