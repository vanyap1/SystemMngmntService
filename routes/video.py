"""V4L2 video devices streamed as MJPEG through ffmpeg."""
import glob
import os
import re
import subprocess

from flask import Blueprint, Response, jsonify, request

from core.auth import login_required

bp = Blueprint('video', __name__)

_DEVICE_RE = re.compile(r'^/dev/video\d+$')
_SIZE_RE = re.compile(r'^\d{3,5}x\d{3,5}$')
FALLBACK_RESOLUTIONS = ['1280x720', '640x480', '320x240']

_active_video_procs = {}


def get_device_resolutions(device):
    if not _DEVICE_RE.match(device) or not os.path.exists(device):
        return FALLBACK_RESOLUTIONS
    try:
        proc = subprocess.run(
            ['ffmpeg', '-f', 'v4l2', '-list_formats', 'all', '-i', device],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4
        )
        resolutions = set()
        for line in proc.stderr.splitlines():
            if 'Raw' in line or 'Compressed' in line or 'video4linux2' in line:
                resolutions.update(re.findall(r'\b(\d{3,5}x\d{3,5})\b', line))
        sorted_res = sorted(resolutions,
                            key=lambda r: int(r.split('x')[0]) * int(r.split('x')[1]),
                            reverse=True)
        return sorted_res or FALLBACK_RESOLUTIONS
    except Exception:
        return FALLBACK_RESOLUTIONS


def _stop_proc(proc):
    try:
        proc.terminate()
        proc.wait(timeout=0.5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def generate_video_stream(device_path, stream_id, resolution='640x480'):
    cmd = ['ffmpeg', '-f', 'v4l2', '-video_size', resolution, '-i', device_path,
           '-r', '25', '-q:v', '5', '-f', 'mpjpeg', '-boundary_tag', 'frame', '-']
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    _active_video_procs[stream_id] = proc
    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            yield chunk
    except GeneratorExit:
        pass
    finally:
        _active_video_procs.pop(stream_id, None)
        _stop_proc(proc)


@bp.route('/api/video_devices')
@login_required
def api_video_devices():
    devices = []
    for path in sorted(glob.glob('/dev/video*')):
        name_file = f"/sys/class/video4linux/{os.path.basename(path)}/name"
        card_name = ''
        try:
            with open(name_file, 'r', encoding='utf-8') as f:
                card_name = f.read().strip()
        except OSError:
            pass
        label = f"{path} ({card_name})" if card_name else path
        devices.append({'path': path, 'name': card_name, 'label': label})
    return jsonify({'devices': devices})


@bp.route('/api/video_resolutions')
@login_required
def api_video_resolutions():
    device = request.args.get('device', '/dev/video1')
    return jsonify({'device': device, 'resolutions': get_device_resolutions(device)})


@bp.route('/api/video_feed')
@login_required
def api_video_feed():
    device = request.args.get('device', '/dev/video1')
    stream_id = request.args.get('sid', 'default')
    resolution = request.args.get('size', '640x480')
    if not _DEVICE_RE.match(device):
        return "Invalid device", 400
    if not os.path.exists(device):
        return "Device not found", 404
    if not _SIZE_RE.match(resolution):
        resolution = '640x480'
    return Response(generate_video_stream(device, stream_id, resolution),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@bp.route('/api/video_stop', methods=['POST'])
@login_required
def api_video_stop():
    stream_id = (request.get_json(silent=True) or {}).get('stream_id')
    if stream_id:
        proc = _active_video_procs.pop(stream_id, None)
        if proc:
            _stop_proc(proc)
    else:
        for proc in list(_active_video_procs.values()):
            _stop_proc(proc)
        _active_video_procs.clear()
    return jsonify({'success': True})
