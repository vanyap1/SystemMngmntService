"""udev service: status and control, event monitor, rules files, udevadm tools."""
import os
import re

from flask import Blueprint, jsonify, request

from core import udev
from core.auth import login_required
from core.shell import quote, resolve_inside, run_command, sh

bp = Blueprint('udev', __name__)

SUBSYSTEM_RE = re.compile(r'^[\w.:-]{1,64}$')


def _device_node(value):
    """A /dev path from the client, or None."""
    return resolve_inside(value, '/dev') if value else None


def _syspath(devpath):
    """``/devices/...`` from the client -> real /sys path, or None."""
    if not devpath:
        return None
    return resolve_inside('/sys' + devpath if devpath.startswith('/devices/') else devpath, '/sys/devices')


def _result(out):
    if out.startswith('Error!'):
        return jsonify({'error': out, 'output': out}), 500
    return jsonify({'success': True, 'output': out})


@bp.route('/api/udev/status')
@login_required
def api_status():
    show = {}
    for line in sh('systemctl show systemd-udevd -p ActiveState,SubState,MainPID,ActiveEnterTimestamp').split('\n'):
        key, _, value = line.partition('=')
        show[key] = value
    rules = udev.list_rules()['files']
    return jsonify({
        'version':  sh('udevadm --version'),
        'active':   show.get('ActiveState', 'unknown'),
        'sub':      show.get('SubState', ''),
        'pid':      show.get('MainPID', ''),
        'since':    show.get('ActiveEnterTimestamp', ''),
        'rules':    {d: sum(1 for f in rules if f['dir'] == d) for d in ('local', 'runtime', 'system')},
        'subsystems': sorted(os.listdir('/sys/class')) if os.path.isdir('/sys/class') else [],
    })


@bp.route('/api/udev/action', methods=['POST'])
@login_required
def api_action():
    """{action: reload|restart|trigger|test|attrs, ...}"""
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action == 'reload':
        return _result(run_command('sudo udevadm control --reload-rules') or 'Rules reloaded')
    if action == 'restart':
        return _result(run_command('sudo systemctl restart systemd-udevd') or 'systemd-udevd restarted')
    if action == 'trigger':
        kind = data.get('kind', 'change')
        if kind not in ('change', 'add'):
            return jsonify({'error': 'Trigger action must be change or add'}), 400
        args = []
        subsystem = (data.get('subsystem') or '').strip()
        if subsystem:
            if not SUBSYSTEM_RE.match(subsystem):
                return jsonify({'error': 'Invalid subsystem'}), 400
            args.append('--subsystem-match=' + quote(subsystem))
        device = (data.get('device') or '').strip()
        if device:
            node = _device_node(device)
            if not node:
                return jsonify({'error': 'Device must be a path inside /dev'}), 400
            args.append('--name-match=' + quote(node))
        if not args and not data.get('all'):
            return jsonify({'error': 'Give a subsystem or a device (or confirm triggering all devices)'}), 400
        cmd = f"sudo udevadm trigger --action={kind} {' '.join(args)}".strip()
        return _result(run_command(cmd, timeout=60) or f"Triggered: {cmd[5:]}")
    if action in ('test', 'attrs'):
        node = _device_node(data.get('device'))
        syspath = _syspath(data.get('devpath'))
        if action == 'attrs':
            if not node and not syspath:
                return jsonify({'error': 'Give a device inside /dev'}), 400
            target = f"--name={quote(node)}" if node else f"--path={quote(syspath)}"
            out = sh(f"udevadm info --attribute-walk {target} 2>&1", timeout=15)
            return jsonify({'success': bool(out), 'output': out or 'No attributes'})
        if not syspath and node:
            devpath = sh(f"udevadm info --query=path --name={quote(node)}")
            syspath = _syspath(devpath)
        if not syspath:
            return jsonify({'error': 'Device not found in /sys/devices'}), 400
        kind = data.get('kind', 'add')
        if kind not in ('add', 'change', 'remove'):
            return jsonify({'error': 'Invalid test action'}), 400
        # udevadm test is a dry run: rules are evaluated and printed, RUN programs are not executed.
        return _result(run_command(f"sudo udevadm test --action={kind} {quote(syspath)} 2>&1", timeout=30))
    return jsonify({'error': 'Unknown action'}), 400


@bp.route('/api/udev/events')
@login_required
def api_events():
    """New monitor events since ``since``; polling keeps ``udevadm monitor`` running."""
    try:
        since = int(request.args.get('since', 0))
    except ValueError:
        since = 0
    return jsonify(udev.monitor.events(since))


@bp.route('/api/udev/events/clear', methods=['POST'])
@login_required
def api_events_clear():
    udev.monitor.clear()
    return jsonify({'success': True})


@bp.route('/api/udev/rules')
@login_required
def api_rules():
    return jsonify(udev.list_rules())


@bp.route('/api/udev/rule')
@login_required
def api_rule():
    try:
        return jsonify(udev.read_rule(request.args.get('dir', ''), request.args.get('name', '')))
    except udev.RuleError as e:
        return jsonify({'error': str(e)}), 404


@bp.route('/api/udev/rule', methods=['POST'])
@login_required
def api_rule_save():
    """Save {name, text} to /etc/udev/rules.d. Syntax problems block the save unless ``force``."""
    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    if not isinstance(text, str):
        return jsonify({'error': 'Invalid text'}), 400
    problems = udev.lint_rules(text)
    if problems and not data.get('force'):
        return jsonify({'error': 'Syntax problems found', 'problems': problems}), 422
    try:
        path = udev.save_rule(data.get('name', ''), text)
    except udev.RuleError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True, 'path': path, 'problems': problems})


@bp.route('/api/udev/rule/check', methods=['POST'])
@login_required
def api_rule_check():
    data = request.get_json(silent=True) or {}
    return jsonify({'problems': udev.lint_rules(str(data.get('text', '')))})


@bp.route('/api/udev/rule/delete', methods=['POST'])
@login_required
def api_rule_delete():
    data = request.get_json(silent=True) or {}
    try:
        path = udev.delete_rule(data.get('name', ''))
    except udev.RuleError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True, 'path': path})
