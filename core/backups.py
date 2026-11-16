"""Project backups: archive target_dir (minus the skip patterns) and deploy an archive in its place
(the keep patterns survive), as one background job with progress.

Patterns (Settings → Backups), one per line, ``#`` = comment, relative to the project directory:
    name/          a folder of that name at any depth (with everything inside)
    name           a file or folder of that name at any depth
    *.log          by mask at any depth (``*``, ``?``, ``[abc]``)
    logs/*         everything inside ``logs`` (the empty folder stays) — a ``/`` inside anchors the pattern
                   to the project root; ``*`` there also crosses sub-folders
    /config.json   a leading ``/`` anchors a single name to the project root
A folder that matches is taken as a whole (its contents are not looked at).

Create: scan → (stop the service if configured and running) → write ``<name>.tar.gz.partial`` → rename.
The archive holds ``<project folder name>/…`` (as ``tar -C parent name`` did). A ``.partial`` file is never listed,
downloaded, deployed or deleted.

Deploy: optional full backup of the current project (skip patterns not applied, .git included) → extract into ``.<name>.deploy-<ts>`` next to the project (the
project is untouched until here; a failure deletes the staging folder) → stop the service → copy the keep matches
from the current project into the new tree → rename project → ``.<name>.old-<ts>``, new tree → project (renamed back
if the second rename fails) → start the service (only if it was running) → delete the old tree.
An archive with one top folder deploys that folder's contents; otherwise its top level is the project.
"""
import fnmatch
import os
import pwd
import re
import shutil
import stat
import tarfile
import threading
import time
from datetime import datetime
from pathlib import PurePosixPath

from core import config
from core.shell import quote, run_command

ARCHIVE_EXTS = ('.tar.gz', '.tgz', '.tar')
PARTIAL = '.partial'
MAX_PATTERNS = 200
LOG_LINES = 400
SERVICE_RE = re.compile(r'^[a-zA-Z0-9_.@:%\-]+\.service$')
SYSTEM_DIRS = {'/', '/home', '/root', '/usr', '/etc', '/var', '/opt', '/srv', '/boot', '/bin', '/sbin', '/lib',
               '/tmp', '/mnt', '/media', '/dev', '/proc', '/sys', '/run'}


class BackupError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


class Cancelled(Exception):
    pass


# ── Patterns ───────────────────────────────────────────────────────────────

def parse_patterns(value):
    """List of patterns from a list or multi-line text; comments / blank lines dropped. Raises BackupError."""
    lines = value.splitlines() if isinstance(value, str) else list(value or [])
    out = []
    for raw in lines:
        p = str(raw).strip()
        if not p or p.startswith('#'):
            continue
        core_ = p.strip('/')
        if not core_ or '\0' in p or len(p) > 200:
            raise BackupError(f'Invalid pattern: {p!r}')
        if '..' in core_.split('/'):
            raise BackupError(f'".." is not allowed in a pattern: {p}')
        out.append(p)
    if len(out) > MAX_PATTERNS:
        raise BackupError(f'Too many patterns (max {MAX_PATTERNS})')
    return out


class Matcher:
    """Matches project-relative POSIX paths against patterns (see the module docstring)."""

    def __init__(self, patterns):
        self.rules = []
        for p in patterns:
            dir_only = p.endswith('/')
            body = p.rstrip('/')
            anchored = body.startswith('/') or '/' in body
            body = body.lstrip('/')
            self.rules.append((p, re.compile(fnmatch.translate(body)), dir_only, anchored))

    def match(self, rel, is_dir):
        """The first pattern that matches ``rel``, or None."""
        base = rel.rsplit('/', 1)[-1]
        for p, rx, dir_only, anchored in self.rules:
            if dir_only and not is_dir:
                continue
            if rx.match(rel if anchored else base):
                return p
        return None


def walk(root, matcher, exclude=(), budget=None, limit=None):
    """Yield (rel, path, is_dir, size, pattern) for every entry under ``root``. ``pattern`` is the matching
    pattern (a matched folder is not entered), ``'(mount)'`` for another filesystem, ``'(panel)'`` for an
    excluded absolute path. Stays on root's filesystem; symlinks are entries, never followed."""
    dev = os.lstat(root).st_dev
    exclude = {os.path.normpath(e) for e in exclude}
    deadline = time.monotonic() + budget if budget else None
    count = 0
    stack = [('', root)]
    while stack:
        rel_dir, path_dir = stack.pop()
        try:
            entries = sorted(os.scandir(path_dir), key=lambda e: e.name)
        except OSError:
            continue
        subdirs = []
        for e in entries:
            count += 1
            if (limit and count > limit) or (deadline and time.monotonic() > deadline):
                raise TimeoutError
            rel = f'{rel_dir}/{e.name}' if rel_dir else e.name
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            is_dir = stat.S_ISDIR(st.st_mode)
            size = st.st_size if stat.S_ISREG(st.st_mode) else 0
            if e.path in exclude:
                yield rel, e.path, is_dir, size, '(panel)'
                continue
            if is_dir and st.st_dev != dev:
                yield rel, e.path, is_dir, 0, '(mount)'
                continue
            pat = matcher.match(rel, is_dir)
            yield rel, e.path, is_dir, size, pat
            if is_dir and not pat:
                subdirs.append((rel, e.path))
        stack.extend(reversed(subdirs))


def preview(skip, keep, max_items=300, budget=5.0):
    """What a backup would skip and a deploy would keep, for the settings page."""
    target = config.target_dir()
    if not os.path.isdir(target):
        raise BackupError(f'Project directory not found: {target}', 404)
    res = {'target': target, 'files': 0, 'bytes': 0, 'skipped': [], 'skipped_count': 0, 'kept': [],
           'unused_skip': [], 'unused_keep': [], 'truncated': False}
    used = set()
    try:
        for rel, _p, is_dir, size, pat in walk(target, Matcher(skip), _auto_excludes(target), budget=budget):
            if pat:
                used.add(pat)
                res['skipped_count'] += 1
                if len(res['skipped']) < max_items:
                    res['skipped'].append({'path': rel + ('/' if is_dir else ''), 'pattern': pat})
            elif not is_dir:
                res['files'] += 1
                res['bytes'] += size
        res['unused_skip'] = [p for p in skip if p not in used]
        found = _keep_matches(target, keep, budget=budget)
        res['kept'] = [{'path': rel + ('/' if d else ''), 'pattern': p} for rel, d, p in found[0][:max_items]]
        res['unused_keep'] = found[1]
    except TimeoutError:
        res['truncated'] = True
    return res


def _keep_matches(root, keep, budget=None):
    """([(rel, is_dir, pattern)], unused patterns) for the keep patterns in ``root``."""
    if not keep:
        return [], []
    found, used = [], set()
    for rel, _p, is_dir, _s, pat in walk(root, Matcher(keep), budget=budget):
        if pat and not pat.startswith('('):
            found.append((rel, is_dir, pat))
            used.add(pat)
    return found, [p for p in keep if p not in used]


# ── Safety checks ──────────────────────────────────────────────────────────

def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip('/') + '/')


def _auto_excludes(target):
    """Absolute paths inside the project that are never archived: the backup folder, the panel itself."""
    out = []
    for p in (config.backup_dir(), config.BASE_DIR):
        if p and _inside(p, target) and os.path.realpath(p) != os.path.realpath(target):
            out.append(os.path.realpath(p))
    return out


def check_deploy_target(target):
    """Reasons why the project directory must not be replaced, or ''."""
    t = os.path.normpath(target or '')
    if not os.path.isabs(t):
        return 'The project directory must be an absolute path'
    real = os.path.realpath(t)
    homes = {u.pw_dir.rstrip('/') for u in pwd.getpwall() if u.pw_dir}
    if real in SYSTEM_DIRS or real in homes or real.count('/') < 2:
        return f'{t} is a system or home directory — set a project folder in Settings → Paths'
    if os.path.isdir(real) and os.path.ismount(real):
        return f'{t} is a mount point'
    if _inside(config.backup_dir(), real):
        return 'The backup directory is inside the project directory — a deploy would delete it'
    if _inside(config.BASE_DIR, real):
        return 'The project directory contains the panel itself — update the panel through Git instead'
    if not os.path.isdir(os.path.dirname(real)):
        return f'Parent folder not found: {os.path.dirname(real)}'
    return ''


# ── Archives ───────────────────────────────────────────────────────────────

def archive_path(filename):
    """Absolute path of an archive in backup_dir (no partial, no folders), or None."""
    name = os.path.basename(filename or '')
    if not name or name != filename or name.startswith('.') or not name.endswith(ARCHIVE_EXTS):
        return None
    root = os.path.realpath(config.backup_dir())
    path = os.path.join(root, name)
    return path if os.path.dirname(os.path.realpath(path)) == root else None


def list_archives():
    busy = busy_files()
    files = []
    for e in os.scandir(config.backup_dir()):
        if e.is_file() and e.name.endswith(ARCHIVE_EXTS) and not e.name.startswith('.'):
            st = e.stat()
            files.append({'name': e.name, 'size': st.st_size, 'mtime': st.st_mtime, 'busy': e.name in busy})
    files.sort(key=lambda x: x['mtime'], reverse=True)
    return files


def timestamped_name(suffix=''):
    return f"{os.path.basename(os.path.normpath(config.target_dir()))}{suffix}_{datetime.now():%Y%m%d_%H%M%S}.tar.gz"


# ── Job ────────────────────────────────────────────────────────────────────

class Job:
    def __init__(self, kind, title, files):
        self.kind, self.title, self.files = kind, title, set(files)
        self.state = 'running'
        self.phase = 'Starting'
        self.done = self.total = 0
        self.error = ''
        self.result = {}
        self.lines = []
        self.started = time.time()
        self.finished = None
        self.cancel = threading.Event()
        self.cancellable = True
        self.lock = threading.Lock()

    def log(self, text):
        with self.lock:
            self.lines.append(f'{datetime.now():%H:%M:%S} {text}')
            del self.lines[:-LOG_LINES]

    def step(self, phase, total=0):
        with self.lock:
            self.phase, self.done, self.total = phase, 0, total
        self.log(phase)

    def add(self, n):
        self.done += n
        if self.cancel.is_set() and self.cancellable:
            raise Cancelled

    def status(self):
        with self.lock:
            return {'kind': self.kind, 'title': self.title, 'state': self.state, 'phase': self.phase,
                    'done': self.done, 'total': self.total, 'error': self.error, 'result': self.result,
                    'log': list(self.lines), 'started': self.started, 'finished': self.finished,
                    'cancellable': self.cancellable and self.state == 'running'}


_job = None
_job_lock = threading.Lock()


def job_status():
    return _job.status() if _job else None


def running():
    return bool(_job and _job.state == 'running')


def busy_files():
    """Archive names the running job reads or writes."""
    return set(_job.files) if running() else set()


def cancel():
    if not running():
        raise BackupError('No backup job is running', 409)
    if not _job.cancellable:
        raise BackupError('The project is being replaced — this step cannot be cancelled', 409)
    _job.cancel.set()
    _job.log('Cancel requested')
    return _job.status()


def _start(job, fn):
    global _job
    with _job_lock:
        if running():
            raise BackupError(f'Another job is running: {_job.title}', 409)
        _job = job

    def run():
        try:
            job.result = fn(job) or {}
            job.state = 'done'
            job.phase = 'Done'
            job.log('Done')
        except Cancelled:
            job.state, job.phase = 'cancelled', 'Cancelled'
            job.log('Cancelled — nothing was changed')
        except Exception as exc:              # noqa: BLE001 — every failure ends up in the job
            job.state, job.phase, job.error = 'error', 'Failed', str(exc)
            job.log(f'ERROR: {exc}')
        finally:
            job.finished = time.time()

    threading.Thread(target=run, name=f'backup-{job.kind}', daemon=True).start()
    return job.status()


# ── Service around a job ───────────────────────────────────────────────────

class _ServicePause:
    """Stops the target service for a block and starts it again only if it was running before."""

    def __init__(self, job, why):
        self.job, self.why, self.name, self.was_active = job, why, config.service_name(), False

    def __enter__(self):
        name = self.name
        if not name or name == 'none' or not SERVICE_RE.match(name):
            self.job.log('No target service — nothing to stop')
            self.name = None
            return self
        from core import updates
        if updates.own_unit() == name:
            self.job.log(f'{name} is the panel itself — not stopped')
            self.name = None
            return self
        self.was_active = run_command(f'systemctl is-active {quote(name)}').strip() == 'active'
        if not self.was_active:
            self.job.log(f'{name} is not running — left as is')
            return self
        self.job.log(f'Stopping {name} ({self.why})')
        out = run_command(f'sudo systemctl stop {quote(name)}', timeout=90)
        if out.startswith('Error!'):
            raise BackupError(f'Could not stop {name}: {out}')
        return self

    def __exit__(self, *exc):
        if self.name and self.was_active:
            self.job.log(f'Starting {self.name}')
            out = run_command(f'sudo systemctl start {quote(self.name)}', timeout=90)
            if out.startswith('Error!'):
                self.job.log(f'WARNING: could not start {self.name}: {out}')
                self.job.result['service_error'] = out
        return False


# ── Create ─────────────────────────────────────────────────────────────────

class _Counting:
    """File wrapper that reports read bytes to the job (progress + cancel)."""

    def __init__(self, f, job):
        self.f, self.job = f, job

    def read(self, n=-1):
        data = self.f.read(n)
        self.job.add(len(data))
        return data


def _write_archive(job, dest, skip, stop_service, label='Archiving'):
    """Archive target_dir into ``dest`` (via dest.partial). Returns a summary dict."""
    target = os.path.normpath(config.target_dir())
    if not os.path.isdir(target):
        raise BackupError(f'Project directory not found: {target}', 404)
    job.step('Scanning the project')
    items, skipped, mounts = [], {}, []
    for rel, path, is_dir, size, pat in walk(target, Matcher(skip), _auto_excludes(target)):
        if job.cancel.is_set():
            raise Cancelled
        if pat == '(mount)':
            mounts.append(rel)
        elif pat:
            skipped[pat] = skipped.get(pat, 0) + 1
        else:
            items.append((rel, path, size))
    total = sum(s for _r, _p, s in items)
    job.log(f'{len(items)} entries, {_human(total)} to archive')
    for pat, n in skipped.items():
        job.log(f'  skipped by {pat}: {n}')
    for m in mounts:
        job.log(f'  skipped (other filesystem): {m}/')
    part = dest + PARTIAL
    top = os.path.basename(target)
    warnings = []
    try:
        with _ServicePause(job, 'consistent archive') if stop_service else _NoPause():
            job.step(f'{label} → {os.path.basename(dest)}', total)
            with tarfile.open(part, 'w:gz', compresslevel=6) as tar:
                tar.add(target, arcname=top, recursive=False)
                for rel, path, _size in items:
                    try:
                        ti = tar.gettarinfo(path, f'{top}/{rel}')
                    except OSError as exc:
                        warnings.append(f'{rel}: {exc.strerror}')
                        continue
                    if ti is None:                      # socket etc.
                        continue
                    if ti.isreg():
                        with open(path, 'rb') as f:
                            tar.addfile(ti, _Counting(f, job))
                    else:
                        tar.addfile(ti)
                        job.add(0)
        os.replace(part, dest)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    for w in warnings[:50]:
        job.log(f'  WARNING: {w}')
    size = os.path.getsize(dest)
    job.log(f'Archive {os.path.basename(dest)}: {_human(size)}')
    return {'archive': os.path.basename(dest), 'size': size, 'files': len(items),
            'skipped': sum(skipped.values()), 'warnings': len(warnings)}


class _NoPause:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def start_create():
    _refuse_if_running()
    name = timestamped_name()
    dest = os.path.join(config.backup_dir(), name)
    if not os.path.isdir(config.backup_dir()):
        raise BackupError(f'Backup directory not found: {config.backup_dir()}', 404)
    skip, stop = parse_patterns(config.backup_skip()), config.backup_stop_service()
    job = Job('create', f'Backup {name}', [name])
    return _start(job, lambda j: _write_archive(j, dest, skip, stop))


# ── Deploy ─────────────────────────────────────────────────────────────────

def _safe_members(tar, job, raw):
    """Members with checked names; reject absolute / '..' paths and paths through an archived symlink."""
    links = set()
    pos = 0
    for m in tar:
        parts = PurePosixPath(m.name).parts
        if m.name.startswith('/') or '..' in parts:
            raise BackupError(f'Unsafe path in the archive: {m.name}')
        name = '/'.join(p for p in parts if p != '.')
        if not name:
            continue
        if any('/'.join(parts[:i]) in links for i in range(1, len(parts))):
            raise BackupError(f'Path through a symlink in the archive: {m.name}')
        if m.islnk() and (m.linkname.startswith('/') or '..' in PurePosixPath(m.linkname).parts):
            raise BackupError(f'Unsafe hard link in the archive: {m.name}')
        if m.ischr() or m.isblk() or m.isfifo():
            job.log(f'  skipped device / fifo: {m.name}')
            continue
        if m.issym():
            links.add(name)
        m.mode &= 0o777                                  # no setuid / setgid / sticky
        new = raw.tell()
        job.add(new - pos)
        pos = new
        yield m


def _top(staging):
    """Folder of the new project inside staging: its only top folder, else staging itself."""
    entries = os.listdir(staging)
    if not entries:
        raise BackupError('The archive is empty')
    if len(entries) == 1:
        one = os.path.join(staging, entries[0])
        if os.path.isdir(one) and not os.path.islink(one):
            return one
    return staging


def _chown_tree(root, uid, gid):
    os.lchown(root, uid, gid)
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            os.lchown(os.path.join(d, n), uid, gid)


def _copy_entry(src, dst, as_root):
    """Copy a file / symlink / folder (whole) keeping mode, times and, as root, the owner."""
    st = os.lstat(src)
    if stat.S_ISDIR(st.st_mode):
        os.mkdir(dst)
        for n in os.listdir(src):
            _copy_entry(os.path.join(src, n), os.path.join(dst, n), as_root)
        shutil.copystat(src, dst, follow_symlinks=False)
    elif stat.S_ISLNK(st.st_mode):
        os.symlink(os.readlink(src), dst)
    elif stat.S_ISREG(st.st_mode):
        shutil.copy2(src, dst, follow_symlinks=False)
    else:
        return
    if as_root:
        os.lchown(dst, st.st_uid, st.st_gid)


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _restore_keep(job, old, new, keep, uid, gid, as_root):
    found, unused = _keep_matches(old, keep)
    for rel, _d, pat in found:
        dst = os.path.join(new, rel)
        parent = os.path.dirname(dst)
        missing = []
        while not os.path.isdir(parent):
            missing.append(parent)
            parent = os.path.dirname(parent)
        for p in reversed(missing):
            os.mkdir(p)
            if as_root:
                os.lchown(p, uid, gid)
        _remove(dst)
        _copy_entry(os.path.join(old, rel), dst, as_root)
        job.log(f'  kept {rel}  ({pat})')
    for p in unused:
        job.log(f'  keep pattern matched nothing: {p}')
    return len(found)


def _deploy(job, src, backup_first, skip, keep, stop_for_backup):
    target = os.path.normpath(config.target_dir())
    parent, base = os.path.dirname(target), os.path.basename(target)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    staging = os.path.join(parent, f'.{base}.deploy-{ts}')
    old = os.path.join(parent, f'.{base}.old-{ts}')
    exists = os.path.isdir(target)
    as_root = os.geteuid() == 0
    result = {'target': target}

    if backup_first and exists:
        name = timestamped_name('_pre_deploy')
        job.files.add(name)
        # A safety copy: everything (.git included) — the skip patterns are for distributable archives.
        r = _write_archive(job, os.path.join(config.backup_dir(), name), [], stop_for_backup,
                           label='Full backup of the current project')
        result['auto_backup'] = r['archive']
    elif backup_first:
        job.log('No current project — no backup needed')

    size = os.path.getsize(src)
    job.step(f'Extracting {os.path.basename(src)}', size)
    os.mkdir(staging, 0o700)
    swapped = False
    try:
        with open(src, 'rb') as raw, tarfile.open(fileobj=raw, mode='r:*') as tar:
            tar.extractall(staging, members=_safe_members(tar, job, raw))
        job.done = size
        new = _top(staging)
        n = sum(len(d) + len(f) for _r, d, f in os.walk(new))
        job.log(f'{n} entries extracted' + ('' if new == staging else f' (top folder {os.path.basename(new)}/)'))
        if exists:
            st = os.stat(target)
            uid, gid, mode = st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)
        else:
            pst = os.stat(parent)
            uid, gid, mode = pst.st_uid, pst.st_gid, 0o755
        if as_root:
            job.step('Setting the owner of the new files')
            _chown_tree(new, uid, gid)
        os.chmod(new, mode)
        if job.cancel.is_set():
            raise Cancelled

        with _ServicePause(job, 'replacing the project'):
            if exists and keep:
                job.step('Restoring kept files')
                result['kept'] = _restore_keep(job, target, new, keep, uid, gid, as_root)
            job.cancellable = False
            job.step('Replacing the project directory')
            if exists:
                os.rename(target, old)
            try:
                os.rename(new, target)
            except OSError:
                if exists:
                    os.rename(old, target)
                raise
            swapped = True
            job.log(f'{target} replaced')
    finally:
        try:
            _remove(staging)
        except OSError as exc:
            job.log(f'WARNING: could not delete {staging}: {exc}')
    if swapped and exists:
        job.step('Deleting the old project')
        try:
            shutil.rmtree(old)
        except OSError as exc:
            job.log(f'WARNING: old project left in {old}: {exc}')
            result['old_left'] = old
    return result


def _refuse_if_running():
    if running():
        raise BackupError(f'Another job is running: {_job.title}', 409)


def start_deploy(filename, backup_first=True):
    _refuse_if_running()
    src = archive_path(filename)
    if not src:
        raise BackupError('Invalid archive name')
    if not os.path.isfile(src):
        raise BackupError('Archive not found', 404)
    reason = check_deploy_target(config.target_dir())
    if reason:
        raise BackupError(reason)
    skip, keep = parse_patterns(config.backup_skip()), parse_patterns(config.deploy_keep())
    stop = config.backup_stop_service()
    job = Job('deploy', f'Deploy {filename}', [filename])
    return _start(job, lambda j: _deploy(j, src, bool(backup_first), skip, keep, stop))


def delete_archive(filename):
    path = archive_path(filename)
    if not path:
        raise BackupError('Invalid archive name')
    if filename in busy_files():
        raise BackupError('The archive is in use by the running job', 409)
    if not os.path.isfile(path):
        raise BackupError('Archive not found', 404)
    os.remove(path)


def _human(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
