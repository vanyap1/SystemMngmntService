"""Move the running system to another disk / build a bootable image on the SMB share / write an image to a disk
(HW Utils -> Clone / Image).

The work is done by ``tools/clone-system.sh`` (rsync of the root filesystem into a new partition of the size of the
used data + reserve + extra, fstab / armbianEnv.txt with the new UUID, u-boot) or ``tools/write-image.sh`` (dd of an
.img / .img.gz / .img.xz / .img.zst from the share, a local disk or a home folder) started with ``spawn.popen`` in its
own session; Stop sends SIGTERM to the whole group (the script unmounts and removes unfinished images).
One job at a time; it keeps running when the browser is closed (the page reattaches to it).
"""
import collections
import json
import os
import re
import signal
import socket
import subprocess
import threading
import time

from core import config, smb, spawn

RESERVE_MB = 300                     # same as the script: free space kept in the minimum partition
SKIP_DISK = re.compile(r'^(loop|zram|ram|mtdblock|nbd)\d*|boot\d+$|rpmb$')
TOOLS = ['rsync', 'sfdisk', 'wipefs', 'blkid', 'lsblk', 'findmnt', 'blockdev', 'mkfs.ext4', 'udevadm', 'losetup']
SBIN = ['/usr/local/sbin', '/usr/sbin', '/sbin', '/usr/local/bin', '/usr/bin', '/bin']
TAG = re.compile(r'^[\w.-]{0,40}$')
PROGRESS = re.compile(r'^\s*([\d,.]+[KMGT]?)\s+(\d{1,3})%\s+(\S+/s)\s+(\d+:\d\d:\d\d)')
DD_PROGRESS = re.compile(r'^(\d+) bytes .*copied, ([\d.,]+) s, ([\d.,]+ \S+/s)')
IMAGE_EXT = re.compile(r'\.(img|img\.gz|img\.xz|img\.zst)$', re.I)
FIND_DEPTH, FIND_MAX, FIND_SECONDS = 5, 300, 8.0
MB = 1024 * 1024


class CloneError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def script(name='clone-system.sh'):
    return os.path.join(config.BASE_DIR, 'tools', name)


def _which(cmd):
    return next((os.path.join(d, cmd) for d in SBIN if os.access(os.path.join(d, cmd), os.X_OK)), None)


def _run(args, timeout=15):
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else ''


def _lsblk():
    out = _run(['lsblk', '-J', '-b', '-o', 'NAME,PATH,SIZE,TYPE,TRAN,MODEL,RM,FSTYPE,LABEL,MOUNTPOINTS,PKNAME'])
    try:
        return json.loads(out).get('blockdevices') or []
    except ValueError:
        return []


def _root_part():
    src = _run(['findmnt', '-n', '-o', 'SOURCE', '/']).strip()
    return re.sub(r'\[.*$', '', src)


def _boot_part():
    src = _run(['findmnt', '-n', '-o', 'SOURCE', '/boot']).strip()
    return src if src and src != _root_part() else ''


def _used_bytes(path):
    try:
        st = os.statvfs(path)
        return (st.f_blocks - st.f_bfree) * st.f_frsize
    except OSError:
        return 0


def _part_start(part):
    try:
        with open(f'/sys/class/block/{os.path.basename(part)}/start') as f:
            return max(8192, int(f.read().strip()))
    except (OSError, ValueError):
        return 8192


def min_partition_mb(used_bytes):
    """Same formula as the script: data + reserve + ~5 % ext4 metadata."""
    return (used_bytes // MB + RESERVE_MB) * 100 // 95 + 1


def _walk(dev, parent=None):
    yield dev, parent
    for ch in dev.get('children') or []:
        yield from _walk(ch, dev)


def disks(tree=None, root_part=None, boot_part=''):
    """Whole disks that can take the system; the one the system runs from is marked ``system`` (not selectable)."""
    tree = _lsblk() if tree is None else tree
    root_part = _root_part() if root_part is None else root_part
    out = []
    for d in tree:
        if d.get('type') != 'disk' or SKIP_DISK.search(d.get('name') or ''):
            continue
        parts, system, mounted = [], False, []
        for dev, _ in _walk(d):
            mps = [m for m in (dev.get('mountpoints') or []) if m]
            if dev.get('path') in (root_part, boot_part):
                system = True
            if dev is not d:
                parts.append({'name': dev.get('name'), 'size': dev.get('size'), 'fstype': dev.get('fstype') or '',
                              'label': dev.get('label') or '', 'mountpoints': mps})
            mounted += mps
        out.append({'name': d.get('name'), 'path': d.get('path'), 'size': int(d.get('size') or 0),
                    'tran': d.get('tran') or '', 'model': (d.get('model') or '').strip(), 'removable': bool(d.get('rm')),
                    'system': system, 'mounted': mounted, 'parts': parts})
    return out


def info():
    root_part, boot_part = _root_part(), _boot_part()
    used = _used_bytes('/') + (_used_bytes('/boot') if boot_part else 0)
    start = _part_start(root_part) if root_part else 8192
    return {
        'root': os.geteuid() == 0,
        'hostname': socket.gethostname(),
        'root_part': root_part, 'boot_part': boot_part,
        'used': used, 'reserve_mb': RESERVE_MB, 'min_mb': min_partition_mb(used),
        'part_start': start,
        'uboot': 'armbian' if os.path.isfile('/usr/lib/u-boot/platform_install.sh') else
                 ('sunxi' if any(os.path.isfile(os.path.join('/usr/lib', d, 'u-boot-sunxi-with-spl.bin'))
                                 for d in os.listdir('/usr/lib') if d.startswith('linux-u-boot-')) else ''),
        'missing': [t for t in TOOLS if not _which(t)],
        'disks': disks(root_part=root_part, boot_part=boot_part),
        'job': job_status(),
    }


# ── Job ─────────────────────────────────────────────────────

class Job:
    def __init__(self, kind, title, env, total=None):
        self.kind, self.title, self.env, self.total = kind, title, env, total
        self.lines = collections.deque(maxlen=3000)
        self.first = 0                       # number of the first line kept
        self.progress = None                 # {'percent', 'done', 'speed', 'eta'}
        self.state = 'running'
        self.rc = None
        self.started, self.finished = time.time(), None
        self.result = ''
        self.proc = None
        self.lock = threading.Lock()

    def add(self, text):
        text = text.rstrip()
        if not text:
            return
        m, dd = PROGRESS.match(text), DD_PROGRESS.match(text)
        with self.lock:
            if m:                            # rsync --info=progress2: keep only the latest value
                self.progress = {'done': m.group(1), 'percent': int(m.group(2)), 'speed': m.group(3), 'eta': m.group(4)}
                return
            if dd and self.total:            # dd status=progress: bytes read of the image file
                done, secs = int(dd.group(1)), float(dd.group(2).replace(',', '.'))
                rate = done / secs if secs else 0
                eta = int((self.total - done) / rate) if rate else 0
                self.progress = {'done': _human(done), 'percent': min(100, done * 100 // self.total), 'speed': dd.group(3),
                                 'eta': f'{eta // 3600}:{eta // 60 % 60:02d}:{eta % 60:02d}'}
                return
            if len(self.lines) == self.lines.maxlen:
                self.first += 1
            self.lines.append(text)
            r = re.match(r'==> Done: (?:image written to|image|system copied to) (\S+)', text)
            if r:
                self.result = r.group(1)

    def status(self, since=0):
        with self.lock:
            since = max(since, self.first)
            lines = list(self.lines)[since - self.first:]
            return {'kind': self.kind, 'title': self.title, 'state': self.state, 'rc': self.rc,
                    'started': self.started, 'finished': self.finished, 'progress': self.progress,
                    'result': self.result, 'next': self.first + len(self.lines), 'lines': lines,
                    'elapsed': (self.finished or time.time()) - self.started}


_job = None
_lock = threading.Lock()


def job_status(since=0):
    return _job.status(since) if _job else None


def busy():
    return bool(_job and _job.state in ('running', 'stopping'))


def _reader(job):
    buf = b''
    try:
        while True:
            chunk = job.proc.stdout.read1(4096) if hasattr(job.proc.stdout, 'read1') else job.proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb'[\r\n]', buf)
            buf = parts.pop()
            for p in parts:
                job.add(p.decode('utf-8', 'replace'))
        if buf:
            job.add(buf.decode('utf-8', 'replace'))
    finally:
        job.proc.stdout.close()
        job.rc = job.proc.wait()
        with job.lock:
            job.finished = time.time()
            job.state = 'stopped' if job.state == 'stopping' or job.rc in (143, -15) else ('ok' if job.rc == 0 else 'error')
        job.add(f'[exit code {job.rc}]')


def _human(n):
    for unit in ('B', 'K', 'M', 'G', 'T'):
        if n < 1024 or unit == 'T':
            return f'{n:.1f}{unit}' if unit != 'B' else f'{n}B'
        n /= 1024


def _start(kind, title, env, name='clone-system.sh', total=None):
    global _job
    if os.geteuid() != 0:
        raise CloneError('The panel runs without root: cloning is not possible here', 403)
    if not os.access(script(name), os.X_OK):
        raise CloneError(f'tools/{name} is missing or not executable', 500)
    with _lock:
        if busy():
            raise CloneError('Another clone / image job is running', 409)
        full = dict(os.environ, PATH=':'.join(SBIN), NO_COLOR='1', ASSUME_YES='yes', LC_ALL='C', **env)
        job = Job(kind, title, env, total)
        job.add(f'$ {" ".join(f"{k}={v}" for k, v in env.items())} {script(name)}')
        job.proc = spawn.popen(['bash', script(name)], env=full, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True, cwd='/')
        _job = job
    threading.Thread(target=_reader, args=(job,), name='sysclone', daemon=True).start()
    return job.status()


def _extra(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise CloneError('Extra size must be a whole number of MiB')
    if not 0 <= v <= 1024 * 1024:
        raise CloneError('Extra size out of range')
    return v


def _target(disk, confirm):
    """A writable target disk from disks(): never the system disk, nothing mounted, its name typed in ``confirm``."""
    d = next((x for x in disks() if x['name'] == disk), None)
    if not d:
        raise CloneError(f'Unknown disk: {disk}', 404)
    if d['system']:
        raise CloneError('The system runs from this disk — it cannot be the target', 403)
    if d['mounted']:
        raise CloneError(f'{d["path"]} has mounted partitions ({", ".join(d["mounted"])}) — unmount them first', 409)
    if (confirm or '').strip() != d['name']:
        raise CloneError(f'Type the disk name "{d["name"]}" to confirm')
    return d


def start_clone(disk, extra_mb=1024, whole=False, confirm='', grow=False):
    """Copy the system to ``disk`` (a name from disks(), never the system disk); ``confirm`` = the typed name."""
    d = _target(disk, confirm)
    env = {'TARGET_DISK': d['path'], 'GROW_ON_BOOT': 'yes' if grow and not whole else 'no'}
    if whole:
        env['TARGET_SIZE_MB'] = 'max'
    else:
        env['EXTRA_MB'] = str(_extra(extra_mb))
    return _start('clone', f'Clone system → {d["path"]}', env)


def image_name(tag='', when=None):
    tag = (tag or '').strip()
    if not TAG.match(tag):
        raise CloneError('Tag: letters, digits, . _ - (max 40)')
    host = re.sub(r'[^\w.-]', '_', socket.gethostname())
    stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime(when))
    return f'{host}_{tag}_{stamp}.img' if tag else f'{host}_{stamp}.img'


def start_image(folder='', extra_mb=1024, tag='', compress='', grow=True):
    """Build ``<host>[_tag]_<date>.img[.gz]`` in ``folder`` of the mounted share."""
    if compress not in ('', 'gz'):
        raise CloneError('Compression: none or gz')
    try:
        target = smb.path_of(folder)
    except smb.SmbError as e:
        raise CloneError(str(e), e.status)
    if not os.path.isdir(target):
        raise CloneError('Folder not found on the share', 404)
    name = image_name(tag)
    env = {'IMAGE_FILE': os.path.join(target, name), 'EXTRA_MB': str(_extra(extra_mb)),
           'GROW_ON_BOOT': 'yes' if grow else 'no'}
    if compress:
        env['COMPRESS'] = compress
    return _start('image', f'Image → {name}{".gz" if compress else ""}', env)


def stop():
    job = _job
    if not job or job.state != 'running':
        raise CloneError('No running job', 409)
    with job.lock:
        job.state = 'stopping'
    try:
        os.killpg(job.proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    return job.status()


# ── Write an image to a disk ───────────────────────────────

def image_roots(disk_list=None):
    """Places to take images from: the mounted SMB share, mounted non-system disks (a local NAS), home folders."""
    roots, seen = [], set()

    def add(path, label, kind):
        real = os.path.realpath(path)
        if real not in seen and os.path.isdir(real):
            seen.add(real)
            roots.append({'path': real, 'label': label, 'kind': kind})
    st = smb.status()
    if st['mounted']:
        add(smb.MOUNT_POINT, 'SMB ' + st['source'].replace('\\', '/'), 'share')
    for d in disk_list if disk_list is not None else disks():
        if d['system']:
            continue
        for m in d['mounted']:
            if m.startswith('/') and m != '/':
                add(m, f'{d["name"]} · {m}', 'disk')
    try:
        homes = sorted(e.path for e in os.scandir('/home') if e.is_dir(follow_symlinks=False))
    except OSError:
        homes = []
    for h in homes:
        add(h, '~' + os.path.basename(h) + ' (' + h + ')', 'home')
    if os.geteuid() == 0:
        add('/root', '~root (/root)', 'home')
    return roots


def _in_root(root, rel=''):
    """(root, absolute path) after checking ``root`` is one of image_roots() and ``rel`` stays inside it."""
    root = os.path.realpath(root or '')
    if root not in {r['path'] for r in image_roots()}:
        raise CloneError('Unknown image location', 404)
    rel = (rel or '').strip().strip('/')
    if '\x00' in rel or any(p == '..' for p in rel.split('/')):
        raise CloneError('Invalid path')
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):
        raise CloneError('Invalid path')
    return root, full


def _entry(path, name, st):
    return {'name': name, 'size': st.st_size, 'mtime': st.st_mtime, 'path': path}


def browse_images(root, rel=''):
    """Folders and image files of a folder (hidden entries and other files are left out)."""
    root, full = _in_root(root, rel)
    if not os.path.isdir(full):
        raise CloneError('Not a folder', 404)
    dirs, files = [], []
    try:
        with os.scandir(full) as it:
            for e in it:
                if e.name.startswith('.'):
                    continue
                try:
                    if e.is_dir(follow_symlinks=True):
                        dirs.append({'name': e.name})
                    elif e.is_file(follow_symlinks=True) and IMAGE_EXT.search(e.name):
                        files.append(_entry(os.path.relpath(e.path, root), e.name, e.stat()))
                except OSError:
                    continue
    except PermissionError:
        raise CloneError('Permission denied', 403)
    except OSError as e:
        raise CloneError(f'Cannot read the folder: {e.strerror}', 502)
    dirs.sort(key=lambda i: i['name'].lower())
    files.sort(key=lambda i: -i['mtime'])
    rel = os.path.relpath(full, root)
    return {'root': root, 'path': '' if rel == '.' else rel, 'dirs': dirs[:MAX_LIST], 'images': files[:MAX_LIST]}


MAX_LIST = 2000


def find_images(root, rel=''):
    """Image files below a folder: depth FIND_DEPTH, FIND_MAX results, FIND_SECONDS budget, one filesystem."""
    root, full = _in_root(root, rel)
    t0, out, truncated = time.time(), [], False
    try:
        dev = os.stat(full).st_dev
    except OSError:
        raise CloneError('Folder not found', 404)
    base_depth = full.rstrip('/').count('/')
    for cur, subdirs, names in os.walk(full):
        if time.time() - t0 > FIND_SECONDS or len(out) >= FIND_MAX:
            truncated = True
            break
        keep = []
        for s in subdirs:
            p = os.path.join(cur, s)
            try:
                if not s.startswith('.') and os.lstat(p).st_dev == dev and p.count('/') - base_depth < FIND_DEPTH:
                    keep.append(s)
            except OSError:
                pass
        subdirs[:] = keep
        for n in names:
            if IMAGE_EXT.search(n) and not n.startswith('.'):
                p = os.path.join(cur, n)
                try:
                    out.append(_entry(os.path.relpath(p, root), n, os.stat(p)))
                except OSError:
                    pass
    out.sort(key=lambda i: -i['mtime'])
    rel = os.path.relpath(full, root)
    return {'root': root, 'path': '' if rel == '.' else rel, 'images': out[:FIND_MAX], 'truncated': truncated}


def start_write(root, path, disk, confirm=''):
    """Write the image ``root``/``path`` onto ``disk`` (same target rules as a clone)."""
    root, full = _in_root(root, path)
    if not os.path.isfile(full) or not IMAGE_EXT.search(full):
        raise CloneError('Not an image file (.img, .img.gz, .img.xz, .img.zst)', 404)
    d = _target(disk, confirm)
    size = os.path.getsize(full)
    if full.lower().endswith('.img') and size > d['size']:
        raise CloneError(f'The image ({size // MB} MiB) is larger than {d["path"]} ({d["size"] // MB} MiB)')
    return _start('write', f'Write {os.path.basename(full)} → {d["path"]}', {'IMAGE': full, 'TARGET_DISK': d['path']},
                  name='write-image.sh', total=size)
