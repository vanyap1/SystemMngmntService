"""Settings → Network: NetworkManager connections and Wi-Fi (core/netcfg.py), access point + DHCP and the network
map (core/netap.py). Every change is pending until the
browser confirms it (POST /api/netcfg/confirm); otherwise NetworkManager rolls it back by itself."""
from flask import Blueprint, jsonify, request

from core import netap, netcfg
from core.auth import login_required

bp = Blueprint('netcfg', __name__)


def _call(fn, *args, **kw):
    try:
        return jsonify(fn(*args, **kw) or {})
    except netcfg.NetError as exc:
        return jsonify({'error': str(exc), 'pending': netcfg.pending()}), exc.status


def _body():
    return request.get_json(silent=True) or {}


@bp.route('/api/netcfg')
@login_required
def overview():
    return _call(netcfg.overview, request.remote_addr or '')


@bp.route('/api/netcfg/pending')
@login_required
def pending():
    return jsonify({'pending': netcfg.pending()})


@bp.route('/api/netcfg/connection')
@login_required
def connection():
    return _call(netcfg.connection, request.args.get('uuid', ''))


@bp.route('/api/netcfg/wifi')
@login_required
def wifi():
    return _call(lambda: {'networks': netcfg.scan(request.args.get('ifname') or None, request.args.get('rescan') == '1')})


@bp.route('/api/netcfg/connection', methods=['POST'])
@login_required
def save():
    d = _body()
    return _call(netcfg.save_connection, d.get('uuid', ''), d, d.get('password') or None)


@bp.route('/api/netcfg/<action>', methods=['POST'])
@login_required
def action(action):
    d = _body()
    fns = {
        'activate':   lambda: netcfg.activate(d.get('uuid', '')),
        'deactivate': lambda: netcfg.deactivate(d.get('uuid', '')),
        'delete':     lambda: netcfg.delete(d.get('uuid', '')),
        'radio':      lambda: netcfg.set_wifi(bool(d.get('on'))),
        'join':       lambda: netcfg.wifi_connect(d.get('ssid', ''), d.get('password', ''), d.get('ifname', ''),
                                                  d.get('security', 'WPA2'), bool(d.get('hidden'))),
        'confirm':    netcfg.confirm,
        'revert':     netcfg.revert,
    }
    if action not in fns:
        return jsonify({'error': 'Unknown action'}), 404
    return _call(fns[action])


# ── Access point + DHCP (core/netap.py) ─────────────────────────────────────

@bp.route('/api/netcfg/ap')
@login_required
def ap_status():
    return _call(netap.status, request.remote_addr or '')


@bp.route('/api/netcfg/ap/clients')
@login_required
def ap_clients():
    return _call(netap.clients)


@bp.route('/api/netcfg/ap', methods=['POST'])
@login_required
def ap_save():
    d = _body()
    return _call(netap.save_settings, d.get('settings') or {}, d.get('password') or None)


@bp.route('/api/netcfg/ap/mode', methods=['POST'])
@login_required
def ap_mode():
    d = _body()
    return _call(netap.set_mode, d.get('mode', ''), d.get('ifname', ''), d.get('uuid', ''),
                 d.get('settings') or None, d.get('password') or None)


@bp.route('/api/netcfg/ap/restart', methods=['POST'])
@login_required
def ap_restart():
    return _call(netap.restart)


@bp.route('/api/netcfg/dhcp/reservations', methods=['POST'])
@login_required
def dhcp_reservations():
    return _call(netap.set_reservations, _body().get('reservations'))


@bp.route('/api/netcfg/map')
@login_required
def net_map():
    return _call(netap.map_data, request.remote_addr or '')
