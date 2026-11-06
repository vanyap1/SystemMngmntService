"""I²C tools of the HW Utils popup (core/i2c.py): bus list, scan, register read / write, device labels. Login only.
The bus is touched only by these POST requests (explicit user actions), never while listing."""
from flask import Blueprint, jsonify, request

from core import i2c
from core.auth import login_required
from core.i2c import I2CError
from core.test_runner import runner

bp = Blueprint('i2c', __name__)

i2c.blocked = lambda: 'A test script is running — I²C access is locked' if runner.is_running() else None


@bp.errorhandler(I2CError)
def _i2c_error(e):
    return jsonify({'error': str(e)}), e.status


def _body():
    return request.get_json(silent=True) or {}


@bp.route('/api/i2c/buses')
@login_required
def api_buses():
    return jsonify(i2c.buses())


@bp.route('/api/i2c/scan', methods=['POST'])
@login_required
def api_scan():
    d = _body()
    return jsonify(i2c.scan(d.get('bus'), d.get('mode', 'auto')))


@bp.route('/api/i2c/read', methods=['POST'])
@login_required
def api_read():
    d = _body()
    return jsonify(i2c.read(d.get('bus'), d.get('addr'), d.get('reg', 0), d.get('width', 1), d.get('length', 1),
                            d.get('force') is True))


@bp.route('/api/i2c/write', methods=['POST'])
@login_required
def api_write():
    d = _body()
    return jsonify(i2c.write(d.get('bus'), d.get('addr'), d.get('data'), d.get('reg', 0), d.get('width', 1),
                             d.get('force') is True))


@bp.route('/api/i2c/label', methods=['POST'])
@login_required
def api_label():
    d = _body()
    return jsonify({'ok': True, 'label': i2c.set_label(d.get('bus'), d.get('addr'), d.get('label', ''))})
