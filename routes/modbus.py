"""Modbus tool of the HW Utils popup (core/modbus.py): read / write / scan over serial RTU, RTU over TCP / UDP,
Modbus TCP / UDP; macro profiles per host in config.json (``modbus``); saved sessions (profile + results + frame log)
as JSON files in ``modbus_sessions_dir``. Login only. Serial ports are locked while a
test script runs (it may own the same UART)."""
from flask import Blueprint, jsonify, request

from core import config, modbus
from core.auth import login_required
from core.modbus import ModbusError
from core.test_runner import runner

bp = Blueprint('modbus', __name__)

modbus.blocked = lambda: 'A test script is running — serial ports are locked' if runner.is_running() else None


@bp.errorhandler(ModbusError)
def _error(e):
    return jsonify({'error': str(e)}), e.status


def _body():
    return request.get_json(silent=True) or {}


@bp.route('/api/modbus/info')
@login_required
def api_info():
    saved = config.get('modbus') or {}
    try:
        profiles = modbus.check_profiles(saved) if saved.get('profiles') else {'profiles': [], 'current': ''}
    except ModbusError:
        profiles = {'profiles': [], 'current': ''}
    return jsonify({'ports': modbus.ports(), 'bauds': modbus.BAUDS, 'funcs': modbus.FUNCS,
                    'transports': modbus.TRANSPORTS, 'blocked': modbus.blocked(), **profiles})


@bp.route('/api/modbus/request', methods=['POST'])
@login_required
def api_request():
    d = _body()
    return jsonify(modbus.run(d.get('conn'), d.get('ops'), d.get('gap_ms', 0)))


@bp.route('/api/modbus/scan', methods=['POST'])
@login_required
def api_scan():
    d = _body()
    return jsonify(modbus.scan(d.get('conn'), d.get('first', 1), d.get('last', 247), d.get('fn', 3), d.get('addr', 0),
                               d.get('timeout')))


@bp.route('/api/modbus/sessions')
@login_required
def api_sessions():
    return jsonify({'sessions': modbus.list_sessions()})


@bp.route('/api/modbus/session')
@login_required
def api_session():
    return jsonify(modbus.load_session(request.args.get('name', '')))


@bp.route('/api/modbus/session/save', methods=['POST'])
@login_required
def api_session_save():
    d = _body()
    return jsonify(modbus.save_session(d.get('name', ''), d.get('data'), bool(d.get('overwrite'))))


@bp.route('/api/modbus/session/delete', methods=['POST'])
@login_required
def api_session_delete():
    return jsonify(modbus.delete_session(_body().get('name', '')))


@bp.route('/api/modbus/profiles', methods=['POST'])
@login_required
def api_profiles():
    data = modbus.check_profiles(_body())
    config.save_key('modbus', data)
    return jsonify(data)
