import os
import re
import json
import subprocess
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, render_template_string, request, redirect, send_file, flash, jsonify, session

app = Flask(__name__)
app.secret_key = "super_secret_key_for_flash_messages"

# Load config
_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
with open(_CONFIG_PATH, 'r', encoding='utf-8') as _f:
    CFG = json.load(_f)

TARGET_DIR   = CFG['target_dir']
BACKUP_DIR   = CFG['backup_dir']
ARCHIVE_NAME = CFG['archive_name']
ARCHIVE_PATH = os.path.join(BACKUP_DIR, ARCHIVE_NAME)
SERVICE_NAME = CFG['service_name']
_AUTH = CFG.get('auth', {})

def require_auth(is_api=False):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if _AUTH.get('enabled') and not session.get('logged_in'):
                if is_api:
                    return jsonify({'error': 'Unauthorized'}), 401
                return redirect('/login?next=' + request.path)
            return f(*args, **kwargs)
        return wrapper
    return decorator
AUTH         = CFG.get('auth', {})

def require_editor_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not AUTH.get('enabled', False):
            return f(*args, **kwargs)
        if session.get('editor_authed'):
            return f(*args, **kwargs)
        return redirect('/login?next=' + request.path)
    return decorated

_LOGIN_HTML = '''
<!DOCTYPE html><html lang="uk"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Login \u2014 {{ page_title }}</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#111;color:#ddd;font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
     display:flex;flex-direction:column;min-height:100vh}
#topbar{background:#1c1c1c;border-bottom:1px solid #2a2a2a;
        padding:10px 24px;display:flex;align-items:center;gap:12px}
.brand{font-size:15px;font-weight:600;color:#e0e0e0}
.sub{font-size:12px;color:#444}
.center{flex:1;display:flex;align-items:center;justify-content:center}
.card{width:340px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;overflow:hidden}
.card-head{background:#222;border-bottom:1px solid #2a2a2a;
           padding:14px 20px;font-size:13px;font-weight:600;color:#aaa;letter-spacing:.4px}
.card-body{padding:24px 20px;display:flex;flex-direction:column;gap:14px}
label{font-size:11px;color:#666;display:block;margin-bottom:4px}
input{width:100%;background:#111;border:1px solid #333;color:#ddd;
      border-radius:5px;padding:8px 10px;font-size:13px;outline:none}
input:focus{border-color:#4a4a4a}
.err{background:#2d1010;border:1px solid #5a2222;color:#e08080;
     border-radius:5px;padding:8px 12px;font-size:12px}
.btn-login{width:100%;padding:9px;font-size:13px;font-weight:600;
           background:#0d3a6e;border:1px solid #1a5fa0;color:#7ec8f5;
           border-radius:5px;cursor:pointer;transition:filter .15s}
.btn-login:hover{filter:brightness(1.2)}
.back{text-align:center;font-size:11px;color:#444}
.back a{color:#4a6a8a;text-decoration:none}
.back a:hover{color:#7ec8f5}
</style></head><body>
<div id="topbar">
  <span class="brand">{{ app_title }}</span>
  <span class="sub">{{ service_name }}</span>
</div>
<div class="center">
  <div class="card">
    <div class="card-head">&#128274; Code Editor &mdash; Login</div>
    <form class="card-body" method="post">
      {% if error %}<div class="err">{{ error }}</div>{% endif %}
      <div>
        <label for="lg">Login</label>
        <input type="text" id="lg" name="login" autocomplete="username" autofocus placeholder="username">
      </div>
      <div>
        <label for="pw">Password</label>
        <input type="password" id="pw" name="password" autocomplete="current-password" placeholder="&bull;&bull;&bull;&bull;&bull;&bull;">
      </div>
      <button type="submit" class="btn-login">Sign in</button>
      <div class="back"><a href="/">&larr; Back to main page</a></div>
    </form>
  </div>
</div>
</body></html>
'''

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if (request.form.get('login') == _AUTH.get('username') and
                request.form.get('password') == _AUTH.get('password')):
            session['logged_in'] = True
            session['editor_authed'] = True
            return redirect(request.args.get('next', '/editor'))
        error = 'Invalid username or password'
    return render_template_string(_LOGIN_HTML, error=error, **_ctx())

@app.route('/logout')
def logout():
    session.pop('editor_authed', None)
    return redirect('/')

def run_command(command):
    try:
        if command.startswith("sudo "):
            command = command.replace("sudo ", "sudo -n ", 1)
            
        result = subprocess.run(command, shell=True, text=True, capture_output=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error!\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"

def _ctx():
    """Common template context from config."""
    return {
        'app_title':    CFG.get('app_title', 'Update Manager'),
        'page_title':   CFG.get('page_title', CFG.get('app_title', 'Update Manager')),
        'service_name': SERVICE_NAME,
        'archive_name': ARCHIVE_NAME,
    }

@app.route('/')
def index():
    status_output = run_command(f"sudo systemctl status {SERVICE_NAME}")
    backup_exists = os.path.exists(ARCHIVE_PATH)
    return render_template('index.html', status=status_output, backup_exists=backup_exists, **_ctx())

@app.route('/service/<action>')
def manage_service(action):
    if action in ['start', 'stop', 'restart']:
        run_command(f"sudo systemctl {action} {SERVICE_NAME}")
        flash(f"Service {SERVICE_NAME} sent command: {action}", "info")
    return redirect('/')

TAR_EXCLUDES = "--exclude='__pycache__' --exclude='.git' --exclude='.vscode'"

def _make_archive(dest_path):
    """Create tar.gz of TARGET_DIR with standard excludes. Returns (success, output)."""
    cmd = (f"sudo tar -czf {dest_path} {TAR_EXCLUDES}"
           f" -C {os.path.dirname(TARGET_DIR)} {os.path.basename(TARGET_DIR)}")
    out = run_command(cmd)
    return ('Error' not in out, out)


@app.route('/backup')
def backup():
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = f"{os.path.basename(TARGET_DIR)}_{ts}.tar.gz"
    path = os.path.join(BACKUP_DIR, name)
    run_command(f"sudo systemctl stop {SERVICE_NAME}")
    ok, out = _make_archive(path)
    run_command(f"sudo systemctl start {SERVICE_NAME}")
    if ok:
        flash(f"Archive created: {name}", "success")
    else:
        flash(f"Error creating archive: {out}", "danger")
    return redirect('/')

@app.route('/download')
def download():
    if os.path.exists(ARCHIVE_PATH):
        return send_file(ARCHIVE_PATH, as_attachment=True)
    flash("Archive file not found!", "danger")
    return redirect('/')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        flash('No file selected', 'danger')
        return redirect('/')
    file = request.files['file']
    if file.filename == '':
        flash('No file selected', 'danger')
        return redirect('/')
    fname = re.sub(r'[^\w.\-]', '_', os.path.basename(file.filename))
    if not (fname.endswith('.tar.gz') or fname.endswith('.tar')):
        flash('Only .tar.gz / .tar files are supported', 'danger')
        return redirect('/')
    dest = os.path.join(BACKUP_DIR, fname)
    file.save(dest)
    flash(f'File "{fname}" uploaded. Select it from the archive list to deploy.', 'success')
    return redirect('/')


@app.route('/api/backups')
def api_backups():
    try:
        files = []
        for e in os.scandir(BACKUP_DIR):
            if e.is_file() and (e.name.endswith('.tar.gz') or e.name.endswith('.tar')):
                st = e.stat()
                files.append({'name': e.name, 'size': st.st_size, 'mtime': st.st_mtime})
        files.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify(files)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/deploy', methods=['POST'])
def deploy():
    data = request.get_json() or {}
    fname = os.path.basename(data.get('filename', ''))
    if not fname:
        return jsonify({'error': 'No filename'}), 400
    src = os.path.join(BACKUP_DIR, fname)
    real_src = os.path.realpath(src)
    if not real_src.startswith(os.path.realpath(BACKUP_DIR) + os.sep):
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.exists(real_src):
        return jsonify({'error': 'File not found'}), 404
    # Auto-backup current project state before deploying
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    auto_name = f"{os.path.basename(TARGET_DIR)}_pre_deploy_{ts}.tar.gz"
    auto_path = os.path.join(BACKUP_DIR, auto_name)
    run_command(f"sudo systemctl stop {SERVICE_NAME}")
    _make_archive(auto_path)
    out = run_command(f"sudo tar -xzf {real_src} -C {os.path.dirname(TARGET_DIR)}")
    run_command(f"sudo systemctl start {SERVICE_NAME}")
    if 'Error' in out:
        return jsonify({'error': out}), 500
    return jsonify({'success': True, 'auto_backup': auto_name})


@app.route('/delete_backup', methods=['POST'])
def delete_backup():
    data = request.get_json() or {}
    fname = os.path.basename(data.get('filename', ''))
    if not fname:
        return jsonify({'error': 'No filename'}), 400
    path = os.path.join(BACKUP_DIR, fname)
    real_path = os.path.realpath(path)
    if not real_path.startswith(os.path.realpath(BACKUP_DIR) + os.sep):
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.exists(real_path):
        return jsonify({'error': 'File not found'}), 404
    os.remove(real_path)
    return jsonify({'success': True})

@app.route('/editor')
@require_editor_auth
def editor():
    return render_template('editor.html', **_ctx())

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

@app.route('/api/tree')
@require_editor_auth
@require_auth(is_api=True)
def api_tree():
    return jsonify(build_file_tree(TARGET_DIR))

@app.route('/api/file', methods=['GET'])
@require_editor_auth
@require_auth(is_api=True)
def api_get_file():
    path = request.args.get('path', '')
    if not path:
        return 'No path provided', 400
    real_path = os.path.realpath(path)
    real_target = os.path.realpath(TARGET_DIR)
    if not real_path.startswith(real_target + os.sep):
        return 'Access denied', 403
    try:
        with open(real_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        return f'Error: {e}', 500

@app.route('/api/file', methods=['POST'])
@require_editor_auth
@require_auth(is_api=True)
def api_save_file():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    path = data.get('path', '')
    content = data.get('content', '')
    if not path:
        return jsonify({'error': 'No path'}), 400
    real_path = os.path.realpath(path)
    real_target = os.path.realpath(TARGET_DIR)
    if not real_path.startswith(real_target + os.sep):
        return jsonify({'error': 'Access denied'}), 403
    try:
        with open(real_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/service/<action>')
@require_auth(is_api=True)
def api_service(action):
    if action not in ['start', 'stop', 'restart']:
        return jsonify({'error': 'Invalid action'}), 400
    name = request.args.get('name', SERVICE_NAME)
    if not re.match(r'^[a-zA-Z0-9_.@:%\-]+\.service$', name):
        return jsonify({'error': 'Invalid service name'}), 400
    output = run_command(f"sudo systemctl {action} {name}")
    return jsonify({'output': output})

@app.route('/api/services')
@require_auth(is_api=True)
def api_services():
    def _sh(cmd):
        try:
            return subprocess.run(cmd, shell=True, text=True,
                                  capture_output=True, timeout=10).stdout.strip()
        except Exception:
            return ''
    raw = _sh("systemctl list-units --type=service --no-legend --no-pager --all 2>/dev/null")
    services = []
    for line in raw.split('\n'):
        stripped = re.sub(r'^[^\w@.-]+', '', line)
        parts = stripped.split(None, 4)
        if len(parts) < 4:
            continue
        name = parts[0]
        if not name.endswith('.service'):
            continue
        services.append({
            'name':   name,
            'load':   parts[1],
            'active': parts[2],
            'sub':    parts[3],
            'desc':   parts[4].strip() if len(parts) > 4 else '',
        })
    return jsonify({'services': services, 'default': SERVICE_NAME})


@app.route('/api/status')
@require_auth(is_api=True)
def api_status():
    name = request.args.get('name', SERVICE_NAME)
    if not re.match(r'^[a-zA-Z0-9_.@:%\-]+\.service$', name):
        name = SERVICE_NAME
    status = run_command(f"sudo systemctl status {name}")
    return status, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/api/sysinfo')
@require_auth(is_api=True)
@require_auth(is_api=True)
def api_sysinfo():
    def sh(cmd, timeout=4):
        try:
            return subprocess.run(cmd, shell=True, text=True,
                                  capture_output=True, timeout=timeout).stdout.strip()
        except Exception:
            return ''

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

    # Process count
    procs = sh("ps -e --no-header | wc -l") or '?'

    # Block devices
    lsblk = sh("lsblk -o NAME,MAJ:MIN,RM,SIZE,RO,TYPE,MOUNTPOINTS 2>/dev/null "
               "|| lsblk -o NAME,MAJ:MIN,RM,SIZE,RO,TYPE,MOUNTPOINT")

    return jsonify({
        'load': load, 'cpu_count': cpu_count,
        'mem': mem, 'net': net,
        'procs': procs, 'lsblk': lsblk,
    })

@app.route('/api/exec', methods=['POST'])
@require_editor_auth
@require_auth(is_api=True)
def api_exec():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    cmd = data.get('cmd', '').strip()
    if not cmd:
        return jsonify({'stdout': '', 'stderr': '', 'returncode': 0})
    try:
        result = subprocess.run(
            cmd, shell=True, text=True, capture_output=True, timeout=30
        )
        return jsonify({'stdout': result.stdout, 'stderr': result.stderr,
                        'returncode': result.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({'stdout': '', 'stderr': 'Timeout (30s)', 'returncode': -1})
    except Exception as e:
        return jsonify({'stdout': '', 'stderr': str(e), 'returncode': -1})

@app.route('/download_backup/<path:filename>')
def download_backup(filename):
    fname = os.path.basename(filename)
    path = os.path.join(BACKUP_DIR, fname)
    real_path = os.path.realpath(path)
    if not real_path.startswith(os.path.realpath(BACKUP_DIR) + os.sep):
        flash('Access denied', 'danger')
        return redirect('/')
    if not os.path.exists(real_path):
        flash('File not found', 'danger')
        return redirect('/')
    return send_file(real_path, as_attachment=True)


@app.route('/api/file_delete', methods=['POST'])
@require_auth(is_api=True)
def api_file_delete():
    data = request.get_json() or {}
    path = data.get('path', '')
    if not path:
        return jsonify({'error': 'No path'}), 400
    real_path = os.path.realpath(path)
    real_target = os.path.realpath(TARGET_DIR)
    if not real_path.startswith(real_target + os.sep):
        return jsonify({'error': 'Access denied'}), 403
    if not os.path.isfile(real_path):
        return jsonify({'error': 'Not a file'}), 404
    try:
        os.remove(real_path)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/file_rename', methods=['POST'])
@require_auth(is_api=True)
def api_file_rename():
    data = request.get_json() or {}
    path = data.get('path', '')
    new_name = re.sub(r'[^\w.\- ]', '_', data.get('new_name', '').strip())
    if not path or not new_name or '/' in new_name or '\\' in new_name:
        return jsonify({'error': 'Invalid request'}), 400
    real_path = os.path.realpath(path)
    real_target = os.path.realpath(TARGET_DIR)
    if not real_path.startswith(real_target + os.sep):
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


@app.route('/api/file_create', methods=['POST'])
@require_auth(is_api=True)
def api_file_create():
    data = request.get_json() or {}
    dir_path = data.get('dir', TARGET_DIR)
    name = re.sub(r'[^\w.\- ]', '_', data.get('name', '').strip())
    if not name:
        return jsonify({'error': 'No name'}), 400
    real_dir = os.path.realpath(dir_path)
    real_target = os.path.realpath(TARGET_DIR)
    if not real_dir.startswith(real_target):
        return jsonify({'error': 'Access denied'}), 403
    new_path = os.path.join(real_dir, name)
    if os.path.exists(new_path):
        return jsonify({'error': 'Already exists'}), 409
    try:
        open(new_path, 'w').close()
        return jsonify({'success': True, 'path': new_path, 'name': name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/file_raw')
@require_auth(is_api=True)
def api_file_raw():
    path = request.args.get('path', '')
    if not path:
        return 'No path', 400
    real_path = os.path.realpath(path)
    real_target = os.path.realpath(TARGET_DIR)
    if not real_path.startswith(real_target + os.sep):
        return 'Access denied', 403
    if not os.path.isfile(real_path):
        return 'Not found', 404
    return send_file(real_path)


@app.route('/api/browse')
@require_auth(is_api=True)
def api_browse():
    """List subdirectories at a given path for the path picker."""
    path = request.args.get('path', '/')
    path = os.path.realpath(path)
    try:
        entries = sorted(
            [e.name for e in os.scandir(path) if e.is_dir() and not e.name.startswith('.')],
            key=str.lower
        )
    except PermissionError:
        entries = []
    parent = str(os.path.dirname(path)) if path != '/' else None
    return jsonify({'path': path, 'parent': parent, 'dirs': entries})


@app.route('/settings', methods=['GET'])
@require_auth()
def settings():
    return render_template('settings.html', cfg=CFG, **_ctx())


@app.route('/settings/save', methods=['POST'])
@require_auth()
def settings_save():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data'}), 400
    try:
        # Update CFG in-place (only allowed keys)
        allowed = ['app_title', 'page_title', 'target_dir', 'backup_dir',
                   'archive_name', 'upload_tmp_name', 'service_name', 'host', 'port']
        for key in allowed:
            if key in data:
                CFG[key] = int(data[key]) if key == 'port' else data[key]
        if 'auth' in data and isinstance(data['auth'], dict):
            CFG.setdefault('auth', {})
            for k in ('enabled', 'username', 'password'):
                if k in data['auth']:
                    CFG['auth'][k] = data['auth'][k]
        with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(CFG, f, indent=4, ensure_ascii=False)
        # Reload runtime constants
        global TARGET_DIR, BACKUP_DIR, ARCHIVE_NAME, ARCHIVE_PATH, SERVICE_NAME, _AUTH
        TARGET_DIR   = CFG['target_dir']
        BACKUP_DIR   = CFG['backup_dir']
        ARCHIVE_NAME = CFG['archive_name']
        ARCHIVE_PATH = os.path.join(BACKUP_DIR, ARCHIVE_NAME)
        SERVICE_NAME = CFG['service_name']
        _AUTH = CFG.get('auth', {})
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host=CFG.get('host', '0.0.0.0'), port=CFG.get('port', 81))