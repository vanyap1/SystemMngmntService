"""Code editor page and file API for target_dir, plus the shell endpoint."""
import os
import re
import subprocess

from flask import Blueprint, jsonify, render_template, request, send_file

from core import config
from core.auth import login_required
from core.shell import resolve_inside

bp = Blueprint('editor', __name__)


def _clean_name(name):
    return re.sub(r'[^\w.\- ]', '_', (name or '').strip())


def build_file_tree(path):
    result = []
    try:
        entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name.startswith('.'):
                continue
            if entry.is_dir():
                result.append({'name': entry.name, 'path': entry.path, 'type': 'dir',
                               'children': build_file_tree(entry.path)})
            else:
                result.append({'name': entry.name, 'path': entry.path, 'type': 'file',
                               'size': entry.stat().st_size})
    except PermissionError:
        pass
    return result


@bp.route('/editor')
@login_required
def editor():
    return render_template('editor.html')


@bp.route('/api/tree')
@login_required
def api_tree():
    return jsonify(build_file_tree(config.target_dir()))


@bp.route('/api/file', methods=['GET'])
@login_required
def api_get_file():
    real_path = resolve_inside(request.args.get('path', ''), config.target_dir())
    if not real_path:
        return 'Access denied', 403
    try:
        with open(real_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f'Error: {e}', 500


@bp.route('/api/file', methods=['POST'])
@login_required
def api_save_file():
    data = request.get_json(silent=True) or {}
    real_path = resolve_inside(data.get('path', ''), config.target_dir())
    if not real_path:
        return jsonify({'error': 'Access denied'}), 403
    try:
        with open(real_path, 'w', encoding='utf-8') as f:
            f.write(data.get('content', ''))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/file_delete', methods=['POST'])
@login_required
def api_file_delete():
    data = request.get_json(silent=True) or {}
    real_path = resolve_inside(data.get('path', ''), config.target_dir())
    if not real_path:
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.isfile(real_path):
        return jsonify({'error': 'Not a file'}), 404
    try:
        os.remove(real_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/file_rename', methods=['POST'])
@login_required
def api_file_rename():
    data = request.get_json(silent=True) or {}
    new_name = _clean_name(data.get('new_name'))
    if not new_name:
        return jsonify({'error': 'Invalid request'}), 400
    real_path = resolve_inside(data.get('path', ''), config.target_dir())
    if not real_path:
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.isfile(real_path):
        return jsonify({'error': 'Not a file'}), 404
    new_path = os.path.join(os.path.dirname(real_path), new_name)
    if os.path.exists(new_path):
        return jsonify({'error': 'Already exists'}), 409
    try:
        os.rename(real_path, new_path)
        return jsonify({'success': True, 'new_path': new_path, 'new_name': new_name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/file_create', methods=['POST'])
@login_required
def api_file_create():
    data = request.get_json(silent=True) or {}
    name = _clean_name(data.get('name'))
    if not name:
        return jsonify({'error': 'No name'}), 400
    target = config.target_dir()
    dir_path = data.get('dir') or target
    real_dir = os.path.realpath(dir_path)
    if real_dir != os.path.realpath(target) and not resolve_inside(dir_path, target):
        return jsonify({'error': 'Access denied'}), 403
    new_path = os.path.join(real_dir, name)
    if os.path.exists(new_path):
        return jsonify({'error': 'Already exists'}), 409
    try:
        open(new_path, 'w').close()
        return jsonify({'success': True, 'path': new_path, 'name': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/file_raw')
@login_required
def api_file_raw():
    real_path = resolve_inside(request.args.get('path', ''), config.target_dir())
    if not real_path:
        return 'Access denied', 403
    if not os.path.isfile(real_path):
        return 'Not found', 404
    return send_file(real_path)


@bp.route('/api/exec', methods=['POST'])
@login_required
def api_exec():
    data = request.get_json(silent=True) or {}
    cmd = data.get('cmd', '').strip()
    if not cmd:
        return jsonify({'stdout': '', 'stderr': '', 'returncode': 0})
    try:
        result = subprocess.run(cmd, shell=True, text=True, capture_output=True, timeout=30)
        return jsonify({'stdout': result.stdout, 'stderr': result.stderr,
                        'returncode': result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({'stdout': '', 'stderr': 'Timeout (30s)', 'returncode': -1})
    except Exception as e:
        return jsonify({'stdout': '', 'stderr': str(e), 'returncode': -1})
