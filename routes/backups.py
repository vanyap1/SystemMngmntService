"""Backup archives of target_dir: create, upload, deploy, download, delete."""
import os
import re
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, request, send_file, url_for

from core import config
from core.auth import login_required
from core.shell import quote, resolve_inside, run_command

bp = Blueprint('backups', __name__)

TAR_EXCLUDES = "--exclude='__pycache__' --exclude='.git' --exclude='.vscode'"
ARCHIVE_EXTS = ('.tar.gz', '.tar')


def _make_archive(dest_path):
    """Create tar.gz of target_dir with standard excludes. Returns (success, output)."""
    target = config.target_dir()
    out = run_command(f"sudo tar -czf {quote(dest_path)} {TAR_EXCLUDES}"
                      f" -C {quote(os.path.dirname(target))} {quote(os.path.basename(target))}")
    return not out.startswith('Error!'), out


def _with_service_stopped(fn):
    service = quote(config.service_name())
    run_command(f"sudo systemctl stop {service}")
    try:
        return fn()
    finally:
        run_command(f"sudo systemctl start {service}")


def _archive_path(filename):
    """Resolve an archive name inside backup_dir or return None."""
    return resolve_inside(os.path.join(config.backup_dir(), os.path.basename(filename or '')),
                          config.backup_dir())


def _timestamped_name(suffix=''):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"{os.path.basename(config.target_dir())}{suffix}_{ts}.tar.gz"


@bp.route('/api/backups')
@login_required
def api_backups():
    try:
        files = []
        for e in os.scandir(config.backup_dir()):
            if e.is_file() and e.name.endswith(ARCHIVE_EXTS):
                st = e.stat()
                files.append({'name': e.name, 'size': st.st_size, 'mtime': st.st_mtime})
        files.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify(files)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@bp.route('/backups/create', methods=['POST'])
@login_required
def create():
    name = _timestamped_name()
    ok, out = _with_service_stopped(
        lambda: _make_archive(os.path.join(config.backup_dir(), name)))
    if ok:
        flash(f"Archive created: {name}", 'success')
    else:
        flash(f"Error creating archive: {out}", 'danger')
    return redirect(url_for('dashboard.index'))


@bp.route('/backups/upload', methods=['POST'])
@login_required
def upload():
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected', 'danger')
        return redirect(url_for('dashboard.index'))
    fname = re.sub(r'[^\w.\-]', '_', os.path.basename(file.filename))
    if not fname.endswith(ARCHIVE_EXTS):
        flash('Only .tar.gz / .tar files are supported', 'danger')
        return redirect(url_for('dashboard.index'))
    file.save(os.path.join(config.backup_dir(), fname))
    flash(f'File "{fname}" uploaded. Select it from the archive list to deploy.', 'success')
    return redirect(url_for('dashboard.index'))


@bp.route('/backups/download/<path:filename>')
@login_required
def download(filename):
    path = _archive_path(filename)
    if not path or not os.path.isfile(path):
        flash('File not found', 'danger')
        return redirect(url_for('dashboard.index'))
    return send_file(path, as_attachment=True)


@bp.route('/api/backups/deploy', methods=['POST'])
@login_required
def deploy():
    data = request.get_json(silent=True) or {}
    src = _archive_path(data.get('filename'))
    if not src:
        return jsonify({'error': 'Invalid filename'}), 400
    if not os.path.isfile(src):
        return jsonify({'error': 'File not found'}), 404
    auto_name = _timestamped_name('_pre_deploy')

    def _deploy():
        # Auto-backup current project state before extracting the archive.
        _make_archive(os.path.join(config.backup_dir(), auto_name))
        return run_command(f"sudo tar -xzf {quote(src)} "
                           f"-C {quote(os.path.dirname(config.target_dir()))}")

    out = _with_service_stopped(_deploy)
    if out.startswith('Error!'):
        return jsonify({'error': out}), 500
    return jsonify({'success': True, 'auto_backup': auto_name})


@bp.route('/api/backups/delete', methods=['POST'])
@login_required
def delete():
    data = request.get_json(silent=True) or {}
    path = _archive_path(data.get('filename'))
    if not path:
        return jsonify({'error': 'Invalid filename'}), 400
    if not os.path.isfile(path):
        return jsonify({'error': 'File not found'}), 404
    os.remove(path)
    return jsonify({'success': True})
