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
STALL_SECONDS = 120                  # no output / progress this long -> look for job processes stuck in the kernel
WATCH_SECONDS = 10                   # job watchdog period
PROBE_SECONDS = 20                   # a share must answer a small write / read within this time
HUNG_GAP = 1.0                       # two /proc samples this far apart: D in both = hung I/O (preflight)


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
        'hung': [] if busy() else hung_io(gap=0.3),     # shown as a warning; preflight refuses a job then
        'stale_loops': [] if busy() else stale_loops(),
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
        self.active = self.started           # last output line / progress update
        self.result = ''
        self.proc = None
        self.lock = threading.Lock()

    def add(self, text):
        text = text.rstrip()
        if not text:
            return
        m, dd = PROGRESS.match(text), DD_PROGRESS.match(text)
        with self.lock:
            self.active = time.time()
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

    def note(self, text):
        """A line from the panel itself (watchdog): logged, but it does not count as output of the job."""
        with self.lock:
            if len(self.lines) == self.lines.maxlen:
                self.first += 1
            self.lines.append(text)

    def status(self, since=0, lines=True):
        with self.lock:
            since = max(since, self.first)
            d = {'kind': self.kind, 'title': self.title, 'state': self.state, 'rc': self.rc,
                 'started': self.started, 'finished': self.finished, 'progress': self.progress,
                 'result': self.result, 'next': self.first + len(self.lines),
                 'elapsed': (self.finished or time.time()) - self.started, 'stall': None}
            if lines:
                d['lines'] = list(self.lines)[since - self.first:]
            quiet = time.time() - self.active
        if d['state'] in ('running', 'stopping') and quiet > STALL_SECONDS:
            d['stall'] = {'quiet': int(quiet), 'stuck': stuck_processes(self.proc.pid) if self.proc else []}
        return d


def _proc_states(proc='/proc', pgid=None):
    """{pid: (state, comm, wchan)} of all processes (or of one process group)."""
    out = {}
    for e in os.listdir(proc):
        if not e.isdigit():
            continue
        try:
            with open(os.path.join(proc, e, 'stat'), encoding='utf-8', errors='replace') as f:
                st = f.read()
            fields = st[st.rindex(')') + 2:].split()
            if pgid is not None and int(fields[2]) != pgid:
                continue
            wchan = ''
            if fields[0] == 'D':
                try:
                    with open(os.path.join(proc, e, 'wchan'), encoding='utf-8') as f:
                        wchan = f.read().strip()
                except OSError:
                    pass
            out[int(e)] = (fields[0], st[st.index('(') + 1:st.rindex(')')], '' if wchan == '0' else wchan)
        except (OSError, ValueError, IndexError):
            continue
    return out


def hung_io(proc='/proc', gap=None):
    """Processes stuck in uninterruptible I/O: state D in two samples ``gap`` s apart. Kernel workers count only
    for loop devices / cifs (flush workers are briefly D under normal load). One such process makes every global
    ``sync`` (sfdisk, mkfs ...) hang, so no job starts while it is there."""
    first = {p: v for p, v in _proc_states(proc).items() if v[0] == 'D'}
    if not first:
        return []
    time.sleep(HUNG_GAP if gap is None else gap)
    out = []
    for pid, (state, comm, wchan) in sorted(_proc_states(proc).items()):
        if state != 'D' or pid not in first or first[pid][1] != comm:
            continue
        if comm.startswith('kworker') and not re.search(r'loop|cifs|smb|deferredclose', comm):
            continue
        out.append({'pid': pid, 'comm': comm, 'wchan': wchan})
    return out


def stale_loops(sys_block='/sys/block'):
    """Loop devices left over by an earlier image job: backed by a file on the share or a ``*.partial`` image."""
    out = []
    try:
        names = sorted(n for n in os.listdir(sys_block) if n.startswith('loop'))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(sys_block, n, 'loop', 'backing_file'), encoding='utf-8', errors='replace') as f:
                back = f.read().strip()
        except OSError:
            continue
        if back.startswith(smb.MOUNT_POINT + '/') or back.endswith('.partial') or back.endswith('.partial (deleted)'):
            out.append({'dev': '/dev/' + n, 'file': back})
    return out


def _bounded(fn, seconds):
    """Run ``fn`` in a thread; (True, result) or (False, None) when it did not return in time (a call on a dead
    share may sleep in the kernel for minutes — the request must not)."""
    box = {}

    def run():
        try:
            box['r'] = fn()
        except Exception as e:  # noqa: BLE001 - reported to the caller
            box['e'] = e
    t = threading.Thread(target=run, daemon=True, name='sysclone-probe')
    t.start()
    t.join(seconds)
    if t.is_alive():
        return False, None
    if 'e' in box:
        raise box['e']
    return True, box.get('r')


def probe_write(folder, seconds=None):
    """Write, read back and delete 1 MiB in ``folder`` within ``seconds``; CloneError when the share hangs / fails."""
    path = os.path.join(folder, f'.smms-probe-{os.getpid()}')
    data = os.urandom(MB)

    def run():
        with open(path, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        with open(path, 'rb') as f:
            back = f.read()
        os.remove(path)
        return back == data
    try:
        ok, same = _bounded(run, PROBE_SECONDS if seconds is None else seconds)
    except OSError as e:
        raise CloneError(f'The share does not accept writes: {e.strerror or e}', 503)
    if not ok:
        raise CloneError(f'The share does not answer (a 1 MiB write / read took over {PROBE_SECONDS} s) — check the '
                         'server / network, then reconnect it', 503)
    if not same:
        raise CloneError('The share returned different data than written (1 MiB test)', 503)


def probe_read(path, seconds=None):
    """Read the first MiB of ``path`` within ``seconds`` (an image on a share / disk that does not answer)."""
    def run():
        with open(path, 'rb') as f:
            return len(f.read(MB))
    try:
        ok, _ = _bounded(run, PROBE_SECONDS if seconds is None else seconds)
    except OSError as e:
        raise CloneError(f'The image cannot be read: {e.strerror or e}', 503)
    if not ok:
        raise CloneError(f'Reading the image takes over {PROBE_SECONDS} s — the share / disk does not answer', 503)


def preflight():
    """Before any job: no hung I/O on the system, no loop device left over by an earlier image job (detached here
    when possible). Raises CloneError with what to do."""
    hung = hung_io()
    if hung:
        names = ', '.join(f'{h["comm"]} (pid {h["pid"]}{", " + h["wchan"] if h["wchan"] else ""})' for h in hung[:6])
        raise CloneError(f'Hung I/O on this system: {names}. Such processes cannot be killed and make disk tools '
                         'hang too — reboot first.', 409)
    for lp in stale_loops():
        _bounded(lambda d=lp['dev']: subprocess.run(['losetup', '-d', d], capture_output=True, timeout=10), 12)
    left = stale_loops()
    if left:
        raise CloneError('Loop device(s) of an earlier image job cannot be detached: ' +
                         ', '.join(f'{x["dev"]} → {x["file"]}' for x in left) + ' — reboot first.', 409)


def stuck_processes(pgid, proc='/proc'):
    """Processes of the job's group in uninterruptible sleep (state D) with the kernel function they wait in —
    a job without output for minutes and such a process usually hangs on I/O (a share, a dying card)."""
    return [{'pid': p, 'comm': c, 'wchan': w} for p, (st, c, w) in sorted(_proc_states(proc, pgid).items()) if st == 'D']


_job = None
_lock = threading.Lock()


def job_status(since=0):
    return _job.status(since) if _job else None


def job_brief():
    """The running job without its log (System Monitor shows it), None when idle."""
    return _job.status(lines=False) if busy() else None


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


def _watch(job):
    """Watchdog: while the job runs, note in its log when it has been quiet for STALL_SECONDS and which of its
    processes are stuck in the kernel (once per change), and when it recovers."""
    last = None
    while job.state in ('running', 'stopping'):
        time.sleep(WATCH_SECONDS)
        if job.state not in ('running', 'stopping'):
            break
        quiet = time.time() - job.active
        if quiet < STALL_SECONDS:
            if last is not None:
                job.note('[watchdog] output again — the job continues')
                last = None
            continue
        stuck = stuck_processes(job.proc.pid) if job.proc else []
        key = tuple((x['pid'], x['wchan']) for x in stuck)
        if key == last:
            continue
        last = key
        if stuck:
            job.note(f'[watchdog] no output for {int(quiet) // 60} min; stuck in the kernel (uninterruptible I/O): ' +
                     ', '.join(f'{x["comm"]} pid {x["pid"]}{" in " + x["wchan"] if x["wchan"] else ""}' for x in stuck) +
                     ' — the device / share does not answer. Stop cannot end such a process; a reboot frees it.')
        else:
            job.note(f'[watchdog] no output for {int(quiet) // 60} min (no process is stuck in the kernel — still working?)')


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
        preflight()
        full = dict(os.environ, PATH=':'.join(SBIN), NO_COLOR='1', ASSUME_YES='yes', LC_ALL='C', **env)
        job = Job(kind, title, env, total)
        job.add(f'$ {" ".join(f"{k}={v}" for k, v in env.items())} {script(name)}')
        job.proc = spawn.popen(['bash', script(name)], env=full, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True, cwd='/')
        _job = job
    threading.Thread(target=_reader, args=(job,), name='sysclone', daemon=True).start()
    threading.Thread(target=_watch, args=(job,), name='sysclone-watch', daemon=True).start()
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
    """A writable target disk from disks(): never the system disk, nothing mounted, ``confirm`` = its name (the UI
    sends it only with the "all data will be destroyed" box ticked)."""
    d = next((x for x in disks() if x['name'] == disk), None)
    if not d:
        raise CloneError(f'Unknown disk: {disk}', 404)
    if d['system']:
        raise CloneError('The system runs from this disk — it cannot be the target', 403)
    if d['mounted']:
        raise CloneError(f'{d["path"]} has mounted partitions ({", ".join(d["mounted"])}) — unmount them first', 409)
    if (confirm or '').strip() != d['name']:
        raise CloneError(f'Confirm that all data on {d["path"]} will be destroyed')
    return d


def start_clone(disk, extra_mb=128, whole=False, confirm='', grow=False):
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


def image_bytes(extra_mb):
    """Size of the image file of the running system (same formula as the script)."""
    root_part = _root_part()
    used = _used_bytes('/') + (_used_bytes('/boot') if _boot_part() else 0)
    start = _part_start(root_part) if root_part else 8192
    return start * 512 + (min_partition_mb(used) + extra_mb) * MB + MB


def start_image(folder='', extra_mb=128, tag='', compress='', grow=True):
    """Build ``<host>[_tag]_<date>.img[.gz]`` in ``folder`` of the mounted share."""
    if compress not in ('', 'gz'):
        raise CloneError('Compression: none or gz')
    try:
        target = smb.path_of(folder)
    except smb.SmbError as e:
        raise CloneError(str(e), e.status)
    ok, isdir = _bounded(lambda: os.path.isdir(target), PROBE_SECONDS)
    if not ok:
        raise CloneError('The share does not answer — check the server / network, then reconnect it', 503)
    if not isdir:
        raise CloneError('Folder not found on the share', 404)
    extra = _extra(extra_mb)
    # the server may allocate the whole (sparse) file at once; gz keeps the raw image until it is compressed
    need = image_bytes(extra) * 3 // 2 if compress else image_bytes(extra)
    st = os.statvfs(target)
    if st.f_bavail * st.f_frsize < need:
        raise CloneError(f'Not enough space on the share: {st.f_bavail * st.f_frsize // MB} MiB free, '
                         f'{need // MB} MiB needed', 507)
    probe_write(target)
    name = image_name(tag)
    env = {'IMAGE_FILE': os.path.join(target, name), 'EXTRA_MB': str(extra),
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
    probe_read(full)
    size = os.path.getsize(full)
    if full.lower().endswith('.img') and size > d['size']:
        raise CloneError(f'The image ({size // MB} MiB) is larger than {d["path"]} ({d["size"] // MB} MiB)')
    return _start('write', f'Write {os.path.basename(full)} → {d["path"]}', {'IMAGE': full, 'TARGET_DISK': d['path']},
                  name='write-image.sh', total=size)
