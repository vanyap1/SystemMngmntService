"""systemd services: list and status are public, actions are checked per action."""
import re

from flask import Blueprint, jsonify, request

from core import auth, config
from core.shell import quote, run_command, sh

bp = Blueprint('services', __name__)

_SERVICE_RE = re.compile(r'^[a-zA-Z0-9_.@:%\-]+\.service$')


def _service_arg():
    name = request.args.get('name') or (request.get_json(silent=True) or {}).get('name')
    return name or config.service_name()


@bp.route('/api/services')
def api_services():
    raw = sh("systemctl list-units --type=service --no-legend --no-pager --all 2>/dev/null",
             timeout=10)
    services = []
    for line in raw.split('\n'):
        stripped = re.sub(r'^[^\w@.-]+', '', line)
        parts = stripped.split(None, 4)
        if len(parts) < 4 or not parts[0].endswith('.service'):
            continue
        services.append({
            'name':   parts[0],
            'load':   parts[1],
            'active': parts[2],
            'sub':    parts[3],
            'desc':   parts[4].strip() if len(parts) > 4 else '',
        })
    return jsonify({'services': services, 'default': config.service_name()})


@bp.route('/api/status')
def api_status():
    name = _service_arg()
    if not _SERVICE_RE.match(name):
        name = config.service_name()
    status = run_command(f"sudo systemctl status {quote(name)}")
    return status, 200, {'Content-Type': 'text/plain; charset=utf-8'}


@bp.route('/api/service/<action>', methods=['POST'])
def api_service(action):
    if action not in config.SERVICE_ACTIONS:
        return jsonify({'error': 'Invalid action'}), 400
    if not auth.can_service_action(action):
        return auth.unauthorized()
    name = _service_arg()
    if not _SERVICE_RE.match(name):
        return jsonify({'error': 'Invalid service name'}), 400
    output = run_command(f"sudo systemctl {action} {quote(name)}")
    return jsonify({'success': not output.startswith('Error!'), 'output': output})
