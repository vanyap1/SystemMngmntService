"""Backup archives of target_dir: create / deploy as a background job (core/backups.py), upload, download, delete."""
import os
import re

from flask import Blueprint, flash, jsonify, redirect, request, send_file, url_for

from core import backups, config
from core.auth import login_required, public_or_login

bp = Blueprint('backups', __name__)


def _err(exc):
    return jsonify({'error': str(exc)}), getattr(exc, 'status', 400)


@bp.route('/api/backups')
@public_or_login('backups')
def api_backups():
    try:
        return jsonify({'archives': backups.list_archives(), 'job': backups.job_status(),
                        'deploy_block': backups.check_deploy_target(config.target_dir()),
                        'target': config.target_dir(), 'keep': backups.parse_patterns(config.deploy_keep()),
                        'stop_service': config.backup_stop_service(), 'service': config.service_name()})
    except (OSError, backups.BackupError) as exc:
        return jsonify({'error': str(exc)}), 500


@bp.route('/api/backups/job')
@public_or_login('backups')
def api_job():
    return jsonify({'job': backups.job_status()})


@bp.route('/api/backups/create', methods=['POST'])
@login_required
def create():
    try:
        return jsonify({'job': backups.start_create()})
    except backups.BackupError as exc:
        return _err(exc)


@bp.route('/api/backups/deploy', methods=['POST'])
@login_required
def deploy():
    data = request.get_json(silent=True) or {}
    try:
        return jsonify({'job': backups.start_deploy(data.get('filename'), data.get('backup', True))})
    except backups.BackupError as exc:
        return _err(exc)


@bp.route('/api/backups/cancel', methods=['POST'])
@login_required
def cancel():
    try:
        return jsonify({'job': backups.cancel()})
    except backups.BackupError as exc:
        return _err(exc)


@bp.route('/api/backups/preview', methods=['POST'])
@login_required
def preview():
    """Settings → Backups: what the (unsaved) patterns would skip / keep in the project directory."""
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(backups.preview(backups.parse_patterns(data.get('skip', '')),
                                       backups.parse_patterns(data.get('keep', ''))))
    except backups.BackupError as exc:
        return _err(exc)


@bp.route('/api/backups/tree', methods=['POST'])
@login_required
def tree():
    """Settings → Backups → project browser: one folder with the (unsaved) skip / keep pattern of each entry."""
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(backups.tree(data.get('path', ''), backups.parse_patterns(data.get('skip', '')),
                                    backups.parse_patterns(data.get('keep', ''))))
    except backups.BackupError as exc:
        return _err(exc)


@bp.route('/backups/upload', methods=['POST'])
@login_required
def upload():
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected', 'danger')
        return redirect(url_for('dashboard.index'))
    fname = re.sub(r'[^\w.\-]', '_', os.path.basename(file.filename)).lstrip('.')
    path = backups.archive_path(fname)
    if not path:
        flash('Only .tar.gz / .tgz / .tar files are supported', 'danger')
        return redirect(url_for('dashboard.index'))
    if fname in backups.busy_files():
        flash(f'"{fname}" is in use by the running job', 'danger')
        return redirect(url_for('dashboard.index'))
    file.save(path + backups.PARTIAL)
    os.replace(path + backups.PARTIAL, path)
    flash(f'File "{fname}" uploaded. Select it from the archive list to deploy.', 'success')
    return redirect(url_for('dashboard.index'))


@bp.route('/backups/download/<path:filename>')
@public_or_login('backups')
def download(filename):
    path = backups.archive_path(filename)
    if not path or not os.path.isfile(path) or filename in backups.busy_files():
        flash('File not found' if filename not in backups.busy_files() else 'The archive is not ready yet', 'danger')
        return redirect(url_for('dashboard.index'))
    return send_file(path, as_attachment=True)


@bp.route('/api/backups/delete', methods=['POST'])
@login_required
def delete():
    data = request.get_json(silent=True) or {}
    try:
        backups.delete_archive(data.get('filename'))
        return jsonify({'success': True})
    except backups.BackupError as exc:
        return _err(exc)
