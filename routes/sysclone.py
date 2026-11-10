"""System clone / image of the HW Utils popup (core/sysclone.py, core/smb.py): move the running system to another
disk, build a bootable image on an SMB share, write an image to a disk, mount and browse the share. Login only; everything that writes
needs an explicit POST (and the typed disk name for a clone)."""
from flask import Blueprint, jsonify, request

from core import smb, sysclone
from core.auth import login_required
from core.smb import SmbError
from core.sysclone import CloneError

bp = Blueprint('sysclone', __name__)


@bp.errorhandler(CloneError)
@bp.errorhandler(SmbError)
def _error(e):
    return jsonify({'error': str(e)}), e.status


def _body():
    return request.get_json(silent=True) or {}


@bp.route('/api/sysclone/info')
@login_required
def api_info():
    d = sysclone.info()
    d['smb'] = smb.status()
    d['roots'] = sysclone.image_roots(d['disks'])
    return jsonify(d)


@bp.route('/api/sysclone/job')
@login_required
def api_job():
    return jsonify({'job': sysclone.job_status(request.args.get('since', 0, type=int))})


@bp.route('/api/sysclone/clone', methods=['POST'])
@login_required
def api_clone():
    d = _body()
    return jsonify({'job': sysclone.start_clone(d.get('disk', ''), d.get('extra_mb', 1024), bool(d.get('whole')),
                                                d.get('confirm', ''), bool(d.get('grow')))})


@bp.route('/api/sysclone/image', methods=['POST'])
@login_required
def api_image():
    d = _body()
    return jsonify({'job': sysclone.start_image(d.get('folder', ''), d.get('extra_mb', 1024), d.get('tag', ''),
                                                d.get('compress', ''), bool(d.get('grow', True)))})


@bp.route('/api/sysclone/roots')
@login_required
def api_roots():
    return jsonify({'roots': sysclone.image_roots()})


@bp.route('/api/sysclone/browse')
@login_required
def api_browse():
    return jsonify(sysclone.browse_images(request.args.get('root', ''), request.args.get('path', '')))


@bp.route('/api/sysclone/find')
@login_required
def api_find():
    return jsonify(sysclone.find_images(request.args.get('root', ''), request.args.get('path', '')))


@bp.route('/api/sysclone/write', methods=['POST'])
@login_required
def api_write():
    d = _body()
    return jsonify({'job': sysclone.start_write(d.get('root', ''), d.get('path', ''), d.get('disk', ''), d.get('confirm', ''))})


@bp.route('/api/sysclone/stop', methods=['POST'])
@login_required
def api_stop():
    return jsonify({'job': sysclone.stop()})


@bp.route('/api/smb/mount', methods=['POST'])
@login_required
def api_smb_mount():
    d = _body()
    pw = d.get('password')
    return jsonify(smb.mount(d.get('share', ''), d.get('username', ''), pw if pw else None,
                             d.get('vers', ''), bool(d.get('remember'))))


@bp.route('/api/smb/umount', methods=['POST'])
@login_required
def api_smb_umount():
    if sysclone.busy() and sysclone.job_status()['kind'] == 'image':
        raise SmbError('An image is being written to the share — stop it first', 409)
    return jsonify(smb.umount())


@bp.route('/api/smb/forget', methods=['POST'])
@login_required
def api_smb_forget():
    return jsonify(smb.forget())


@bp.route('/api/smb/list')
@login_required
def api_smb_list():
    return jsonify(smb.listdir(request.args.get('path', '')))


@bp.route('/api/smb/mkdir', methods=['POST'])
@login_required
def api_smb_mkdir():
    d = _body()
    return jsonify(smb.mkdir(d.get('path', ''), d.get('name', '')))
