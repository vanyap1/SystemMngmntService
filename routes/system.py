"""System info, power management and directory browsing."""
import os
import subprocess

from flask import Blueprint, jsonify, request

from core.auth import login_required
from core.shell import sh

bp = Blueprint('system', __name__)


@bp.route('/api/sysinfo')
@login_required
def api_sysinfo():
    # CPU – load average
    la = sh("cat /proc/loadavg").split()
    load = {'1': la[0], '5': la[1], '15': la[2]} if len(la) >= 3 else {}
    cpu_count = int(sh("nproc") or 1)

    # Memory from /proc/meminfo (values in kB)
    meminfo = {}
    for line in sh("cat /proc/meminfo").split('\n'):
        p = line.split()
        if len(p) >= 2:
            meminfo[p[0].rstrip(':')] = int(p[1])
    mt = meminfo.get('MemTotal', 0)
    ma = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
    st = meminfo.get('SwapTotal', 0)
    sf = meminfo.get('SwapFree', 0)
    mem = {
        'total_kb': mt, 'used_kb': mt - ma, 'avail_kb': ma,
        'pct': round((mt - ma) * 100 / mt) if mt else 0,
        'swap_total_kb': st, 'swap_used_kb': st - sf,
        'swap_pct': round((st - sf) * 100 / st) if st else 0,
    }

    # Network
    net = []
    for line in sh("ip -br addr show").split('\n'):
        p = line.split()
        if p and p[0] != 'lo':
            net.append({'iface': p[0], 'state': p[1] if len(p) > 1 else '',
                        'addrs': p[2:] if len(p) > 2 else []})

    procs = sh("ps -e --no-header | wc -l") or '?'

    lsblk = sh("lsblk -o NAME,MAJ:MIN,RM,SIZE,RO,TYPE,MOUNTPOINTS 2>/dev/null "
               "|| lsblk -o NAME,MAJ:MIN,RM,SIZE,RO,TYPE,MOUNTPOINT")

    return jsonify({
        'load': load, 'cpu_count': cpu_count,
        'mem': mem, 'net': net,
        'procs': procs, 'lsblk': lsblk,
    })


@bp.route('/api/power/<action>', methods=['POST'])
@login_required
def api_power(action):
    if action not in ('reboot', 'poweroff'):
        return jsonify({'error': 'Invalid power action'}), 400
    subprocess.Popen(f"sleep 1 && sudo systemctl {action}", shell=True)
    msg = 'Reboot initiated...' if action == 'reboot' else 'Shutdown initiated...'
    return jsonify({'success': True, 'message': msg})


@bp.route('/api/browse')
@login_required
def api_browse():
    """List subdirectories at a given path for the path picker."""
    path = os.path.realpath(request.args.get('path', '/'))
    try:
        entries = sorted(
            [e.name for e in os.scandir(path) if e.is_dir() and not e.name.startswith('.')],
            key=str.lower
        )
    except (PermissionError, FileNotFoundError, NotADirectoryError):
        entries = []
    parent = os.path.dirname(path) if path != '/' else None
    return jsonify({'path': path, 'parent': parent, 'dirs': entries})
