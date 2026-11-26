"""Network interfaces overview (HW Utils → Network) and the SocketCAN tool (HW Utils → CAN): link, frames,
send, recording, trace player and the trace files."""
import os

from flask import Blueprint, jsonify, request, send_file

from core import can_trace, config, net, pyrun
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
    """{iface, action: send|cyclic|update|stop|stop_all|clear, id, ext, rtr, data, period_ms, job, tag,
    cs: toyota|sum8|xor8, cnt: {byte, bits}} — cs / cnt are applied to every transmission (net.apply_mods)"""
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'send')
    try:
        bus = net.can_bus(data.get('iface'))
        mods = {'cs': data.get('cs'), 'cnt': data.get('cnt')}
        if action == 'send':
            bus.send(data.get('id'), data.get('ext'), data.get('rtr'), data.get('data'), **mods)
        elif action == 'cyclic':
            return jsonify({'success': True, 'job': bus.start_cyclic(
                data.get('id'), data.get('ext'), data.get('rtr'), data.get('data'), data.get('period_ms'),
                data.get('tag', ''), **mods)})
        elif action == 'update':
            bus.update_cyclic(int(data.get('job', -1)), data.get('id'), data.get('ext'), data.get('rtr'),
                              data.get('data'), data.get('period_ms'), **mods)
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


# ── CAN traces: recording, player, files (HW Utils → CAN) ──────────────────

@bp.route('/api/net/can/watch')
@login_required
def api_can_watch():
    """?iface=&key=&since= — every frame of one ID for the analyser (polling keeps the watch and the socket)."""
    try:
        since = int(request.args.get('since', 0))
        return jsonify(net.can_bus(request.args.get('iface')).watch(request.args.get('key', ''), since))
    except ValueError:
        return _error('since must be a number')
    except can_trace.TraceError as e:
        return _error(e, e.status)
    except net.NetError as e:
        return _error(e, 409)


@bp.route('/api/net/can/watch', methods=['POST'])
@login_required
def api_can_watch_stop():
    """{iface} — end the analyser's watch."""
    data = request.get_json(silent=True) or {}
    try:
        net.can_bus(data.get('iface')).watch_stop()
    except net.NetError as e:
        return _error(e)
    return jsonify({'success': True})


@bp.route('/api/net/can/record', methods=['POST'])
@login_required
def api_can_record():
    """{iface, action: start|stop, path, append}"""
    data = request.get_json(silent=True) or {}
    try:
        bus = net.can_bus(data.get('iface'))
        if data.get('action') == 'start':
            return jsonify({'success': True, 'path': bus.record_start(
                can_trace.file_name(data.get('path')), bool(data.get('append')))})
        if data.get('action') == 'stop':
            bus.record_stop()
            return jsonify({'success': True})
        return _error('Unknown action')
    except can_trace.TraceError as e:
        return _error(e, e.status)
    except net.NetError as e:
        return _error(e, 409)


@bp.route('/api/net/can/play', methods=['POST'])
@login_required
def api_can_play():
    """{iface, action: start|pause|resume|stop|set, path, mode: view|bus, speed, loop, skip: [ID keys]}"""
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    try:
        bus = net.can_bus(data.get('iface'))
        if action == 'start':
            if data.get('mode') == 'bus' and (runner.is_running() or pyrun.active()):
                return _error('A test script is running — replay onto the bus is locked', 409)
            return jsonify({'success': True, 'path': bus.play_start(
                data.get('path'), data.get('mode', 'view'), data.get('speed', 1), data.get('loop'), data.get('skip'))})
        bus.play_control(action, data.get('speed'), data.get('loop'), data.get('skip'))
        return jsonify({'success': True})
    except can_trace.TraceError as e:
        return _error(e, e.status)
    except net.NetError as e:
        return _error(e, 409)


@bp.route('/api/can/profiles')
@login_required
def api_can_profiles():
    """TX lists + notes of HW Utils → CAN (config.json ``can``, per host)."""
    try:
        return jsonify(net.check_profiles(config.get('can') or {}))
    except net.NetError:
        return jsonify({'profiles': [], 'current': ''})


@bp.route('/api/can/profiles', methods=['POST'])
@login_required
def api_can_profiles_save():
    try:
        data = net.check_profiles(request.get_json(silent=True) or {})
    except net.NetError as e:
        return _error(e)
    config.save_key('can', data)
    return jsonify(data)


@bp.route('/api/can/traces')
@login_required
def api_can_traces():
    return jsonify({'tree': can_trace.tree()})


@bp.route('/api/can/traces/info')
@login_required
def api_can_trace_info():
    """Summary of one file: frame count, duration, sessions, IDs (with counts)."""
    try:
        path, rel = can_trace.existing_file(request.args.get('path'))
        info, _index = can_trace.scan(path)
    except can_trace.TraceError as e:
        return _error(e, e.status)
    except OSError as e:
        return _error(e.strerror or e, 500)
    return jsonify(dict(info, path=rel))


@bp.route('/api/can/traces/frames')
@login_required
def api_can_trace_frames():
    """?path=&start=&limit=&key= — a page of frames of one file (``key`` = only that ID)."""
    try:
        return jsonify(can_trace.read_frames(request.args.get('path'), request.args.get('start', 0),
                                             request.args.get('limit', 500), request.args.get('key') or None))
    except ValueError:
        return _error('start / limit must be numbers')
    except can_trace.TraceError as e:
        return _error(e, e.status)
    except OSError as e:
        return _error(e.strerror or e, 500)


@bp.route('/api/can/traces', methods=['POST'])
@login_required
def api_can_traces_action():
    """{action: mkdir|rename|delete, path, name}"""
    data = request.get_json(silent=True) or {}
    action, path = data.get('action'), data.get('path')
    try:
        if action == 'mkdir':
            result = can_trace.mkdir(path)
        elif action == 'rename':
            result = can_trace.rename(path, data.get('name'))
        elif action == 'delete':
            result = can_trace.delete(path)
        else:
            return _error('Unknown action')
    except can_trace.TraceError as e:
        return _error(e, e.status)
    except OSError as e:
        return _error(e.strerror or e, 500)
    return jsonify({'success': True, 'path': result, 'tree': can_trace.tree()})


@bp.route('/api/can/traces/upload', methods=['POST'])
@login_required
def api_can_traces_upload():
    """multipart: file, folder"""
    f = request.files.get('file')
    if not f:
        return _error('No file')
    try:
        rel = can_trace.save_upload(request.form.get('folder', ''), f.filename, f.stream)
    except can_trace.TraceError as e:
        return _error(e, e.status)
    except OSError as e:
        return _error(e.strerror or e, 500)
    return jsonify({'success': True, 'path': rel, 'tree': can_trace.tree()})


@bp.route('/api/can/traces/download')
@login_required
def api_can_traces_download():
    try:
        path, rel = can_trace.existing_file(request.args.get('path'))
    except can_trace.TraceError as e:
        return _error(e, e.status)
    return send_file(path, mimetype='text/plain', as_attachment=True, download_name=os.path.basename(rel))
