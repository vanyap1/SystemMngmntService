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


TREE_LIMIT = 3000     # entries per folder sent to the browser


def list_dir(path):
    """One level of the file tree (folders are loaded when opened, so a huge mounted disk is never walked).
    Returns (entries, truncated)."""
    result = []
    try:
        with os.scandir(path) as it:
            entries = [e for e in it if not e.name.startswith('.')]
    except OSError:
        return result, False

    def is_dir(e):
        try:
            return e.is_dir()
        except OSError:
            return False
    entries.sort(key=lambda e: (not is_dir(e), e.name.lower()))
    for entry in entries[:TREE_LIMIT]:
        if is_dir(entry):
            result.append({'name': entry.name, 'path': entry.path, 'type': 'dir', 'link': entry.is_symlink()})
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = None
            result.append({'name': entry.name, 'path': entry.path, 'type': 'file', 'size': size})
    return result, len(entries) > TREE_LIMIT


@bp.route('/editor')
@login_required
def editor():
    return render_template('editor.html')


@bp.route('/api/tree')
@login_required
def api_tree():
    """Entries of one folder of target_dir (?path=, default: target_dir itself)."""
    root = config.target_dir()
    path = os.path.normpath(request.args.get('path') or root)
    if os.path.realpath(path) != os.path.realpath(root) and not resolve_inside(path, root):
        return jsonify({'error': 'Folder is outside target_dir'}), 403
    if not os.path.isdir(path):
        return jsonify({'error': 'Not a folder'}), 404
    entries, truncated = list_dir(path)
    return jsonify({'path': path, 'entries': entries, 'truncated': truncated, 'limit': TREE_LIMIT})


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


TEST_TEMPLATE = '''"""{title}: what this test checks (the first docstring line is shown on the Tests page)."""
from testStrategy import TestStrategy

ts = TestStrategy()


def steps():
    ts.section("Checks")
    ts.logResult("Example step", True, "OK")
    ts.numericLimitTest("Example value", 5.0, 4.5, 5.5, "V")


def finalize():
    pass                                        # bring the fixture to a safe state: outputs off, ports closed


ts.run(steps, finalize)
'''


def _same_owner(path, folder):
    """New files of the panel (root) belong to the owner of their folder, so they stay editable over SSH."""
    if os.geteuid() != 0:
        return
    try:
        st = os.stat(folder)
        os.chown(path, st.st_uid, st.st_gid)
    except OSError:
        pass


@bp.route('/api/file_create', methods=['POST'])
@login_required
def api_file_create():
    """New empty file (or folder: kind="dir") in ``dir`` (default target_dir). A new ``*_test.py`` gets the
    skeleton of a test script."""
    data = request.get_json(silent=True) or {}
    name = _clean_name(data.get('name'))
    if not name or name in ('.', '..') or name.startswith('.'):
        return jsonify({'error': 'Invalid name'}), 400
    target = config.target_dir()
    dir_path = data.get('dir') or target
    real_dir = os.path.realpath(dir_path)
    if real_dir != os.path.realpath(target) and not resolve_inside(dir_path, target):
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.isdir(real_dir):
        return jsonify({'error': 'Folder does not exist'}), 404
    new_path = os.path.join(real_dir, name)
    if os.path.lexists(new_path):
        return jsonify({'error': f'{name} already exists'}), 409
    kind = 'dir' if data.get('kind') == 'dir' else 'file'
    try:
        if kind == 'dir':
            os.mkdir(new_path)
        else:
            with open(new_path, 'x', encoding='utf-8') as f:
                if name.endswith('_test.py'):
                    f.write(TEST_TEMPLATE.format(title=name[:-len('_test.py')].replace('_', ' ').capitalize()))
        _same_owner(new_path, real_dir)
        return jsonify({'success': True, 'path': new_path, 'name': name, 'kind': kind})
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
