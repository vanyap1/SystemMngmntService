"""Update check of the panel itself (the git repository the panel runs from, id 'panel').

While the UI polls /api/update/status, a background thread runs `git fetch` of the upstream at most every
``update_check_minutes`` (sooner again after a failure, e.g. no internet) and reports the commits HEAD is behind.
Applying an update is `git pull --ff-only` through git_ops (as the repo owner, token via the credential helper);
the panel then restarts its own systemd unit on request. Nothing runs while nobody has the panel open.

Forced update (Git panel → Update panel): ``plan()`` fetches and lists what is in the way (local commits, modified
files, untracked files the update would overwrite); ``force_update()`` saves them (backup branch, git stash, copies
in <git dir>/panel-update-backup/), resets the branch to its upstream — ``KEEP`` files (live host settings) stay as
they are — and restarts the panel's unit.
"""
import os
import shutil
import subprocess
import threading
import time

from core import config, git_ops
from core.git_ops import GitError

FETCH_TIMEOUT = 30
RETRY_MINUTES = 10          # after a failed fetch (offline) try again sooner than the interval
MAX_COMMITS = 20
BOOT = time.time()        # lets the UI see that a restarted panel answers
KEEP = ('config.json',)   # live host settings / credentials in the tracked config: never replaced by an update

_lock = threading.Lock()
_state = {'checked': 0.0, 'checking': False, 'online': None, 'branch': None, 'upstream': None,
          'behind': 0, 'ahead': 0, 'dirty': 0, 'remote_oid': None, 'commits': [], 'error': ''}


def own_unit():
    """systemd unit the panel runs in (from /proc/self/cgroup), or None (e.g. a dev server in a terminal)."""
    try:
        with open('/proc/self/cgroup') as fh:
            for line in fh:
                last = line.strip().rsplit('/', 1)[-1]
                if last.endswith('.service') and not last.startswith(('user@', 'session-')):
                    return last
    except OSError:
        pass
    return None


def _check():
    res = {'checked': time.time(), 'online': None, 'branch': None, 'upstream': None, 'behind': 0, 'ahead': 0,
           'dirty': 0, 'remote_oid': None, 'commits': [], 'error': ''}
    try:
        repo = git_ops.Repo('panel')
        st = repo.status()
        res.update(branch=st['branch'], upstream=st['upstream'])
        if not st['upstream']:
            return res
        try:
            with git_ops._lock(repo.top):
                repo.run('fetch', '--quiet', timeout=FETCH_TIMEOUT, network=True)
            res['online'] = True
        except GitError as e:
            res['online'] = False
            res['error'] = str(e)
        st = repo.status()
        res.update(ahead=st['ahead'], behind=st['behind'],
                   dirty=sum(f['kind'] != 'untracked' for f in st['files']))
        rc, out, _ = git_ops._run_raw(repo.top, ['rev-parse', '--verify', '-q', '@{u}'])
        res['remote_oid'] = out.strip() if rc == 0 else None
        if st['behind']:
            res['commits'] = repo.log(MAX_COMMITS, 'HEAD..@{u}')
    except GitError as e:
        res['error'] = str(e)
    return res


def _worker():
    res = _check()
    with _lock:
        _state.update(res, checking=False)


def _due(now):
    minutes = config.update_check_minutes()
    if not minutes:
        return False
    if _state['online'] is False:
        minutes = min(minutes, RETRY_MINUTES)
    return now - _state['checked'] >= minutes * 60


def status(force=False):
    """Last known update state; starts a background check when one is due (or ``force``)."""
    with _lock:
        if not _state['checking'] and (force or _due(time.time())):
            _state['checking'] = True
            threading.Thread(target=_worker, name='update-check', daemon=True).start()
        st = dict(_state)
    st['enabled'] = config.update_check_minutes() > 0
    st['available'] = st['behind'] > 0
    st['can_restart'] = own_unit() is not None
    st['boot'] = BOOT
    return st


def apply():
    """Fast-forward the panel to its upstream. Returns {'message', 'restart'} (restart = the new code needs it)."""
    repo = git_ops.Repo('panel')
    before = repo.run('rev-parse', 'HEAD').strip()
    out = repo.pull('ff')
    after = repo.run('rev-parse', 'HEAD').strip()
    with _lock:
        _state['checking'] = True
    _worker()
    return {'message': out or 'Already up to date', 'restart': before != after}


class UpdateBlocked(GitError):
    """Local changes are in the way of a forced update; ``plan`` says which (the UI asks for a confirmation)."""
    def __init__(self, p):
        super().__init__('Local changes are in the way: ' + '; '.join(p['issues']), 409)
        self.plan = p


def plan():
    """Fetch the panel repository and describe a forced update of it (nothing is changed)."""
    repo = git_ops.Repo('panel')
    st = repo.status()
    if not st['branch']:
        raise GitError('The panel repository is on a detached HEAD — check out a branch first', 409)
    if not st['upstream']:
        raise GitError(f'Branch {st["branch"]} has no upstream to update from', 409)
    with git_ops._lock(repo.top):
        repo.run('fetch', '--quiet', timeout=FETCH_TIMEOUT, network=True)
    st = repo.status()
    incoming = {p for p in repo.run('diff', '--name-only', '-z', 'HEAD', '@{u}').split('\0') if p}
    changed = [f['path'] for f in st['files'] if f['kind'] != 'untracked' and f['path'] not in KEEP]
    in_way = [f['path'] for f in st['files'] if f['kind'] == 'untracked' and f['path'] in incoming]
    kept = [f['path'] for f in st['files'] if f['path'] in KEEP]
    issues = []
    if st['ahead']:
        issues.append(f'{st["ahead"]} local commit(s) are not on {st["upstream"]} — they stay on a backup branch, '
                      f'{st["branch"]} is reset to {st["upstream"]}')
    if changed:
        issues.append(f'{len(changed)} locally modified file(s) are replaced by the repository version '
                      f'(the changes are saved with git stash)')
    if in_way:
        issues.append(f'{len(in_way)} untracked file(s) are overwritten by new files of the update '
                      f'(copies are kept in the git directory)')
    return {'branch': st['branch'], 'upstream': st['upstream'], 'behind': st['behind'], 'ahead': st['ahead'],
            'commits': repo.log(MAX_COMMITS, 'HEAD..@{u}') if st['behind'] else [],
            'changed': changed, 'in_way': in_way, 'kept': kept, 'issues': issues,
            'can_restart': own_unit() is not None, 'boot': BOOT}


def force_update(confirmed=False, restart_after=True):
    """Bring the panel to its upstream whatever is local (see plan()); raises GitError 409 with the plan when there
    are issues and ``confirmed`` is false. Returns {'message', 'plan', 'changed' (code changed), 'restart' (unit)}."""
    p = plan()
    if p['issues'] and not confirmed:
        raise UpdateBlocked(p)
    repo = git_ops.Repo('panel')
    notes = []
    with git_ops._lock(repo.top):
        before = repo.run('rev-parse', 'HEAD').strip()
        keep = {}
        for rel in KEEP:
            path = os.path.join(repo.top, rel)
            if os.path.isfile(path):
                with open(path, 'rb') as f:
                    keep[path] = f.read()
        stamp = time.strftime('%Y%m%d-%H%M%S')
        dest = os.path.join(repo.git_dir(), 'panel-update-backup', stamp)
        for path, data in keep.items():                      # a copy in case the panel dies before restoring them
            os.makedirs(dest, exist_ok=True)
            with open(os.path.join(dest, os.path.basename(path)), 'wb') as f:
                f.write(data)
        if p['ahead'] or p['changed']:
            repo.run('branch', f'backup/{stamp}')
            notes.append(f'backup branch backup/{stamp}')
        if p['changed']:
            repo.run('stash', 'push', '-q', '-m', f'panel update {stamp}')       # tracked changes only
            notes.append('local changes: git stash list')
        if p['in_way']:
            for rel in p['in_way']:
                os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
                shutil.copy2(os.path.join(repo.top, rel), os.path.join(dest, rel))
            notes.append(f'overwritten untracked files copied to {dest}')
        _chown_tree(os.path.join(repo.git_dir(), 'panel-update-backup'), repo.top)
        try:
            repo.run('reset', '--hard', '-q', '@{u}')
        finally:
            for path, data in keep.items():                  # the host settings stay, also when the reset failed
                with open(path, 'wb') as f:
                    f.write(data)
        after = repo.run('rev-parse', 'HEAD').strip()
    with _lock:
        _state['checking'] = True
    _worker()
    code_changed = before != after or bool(p['changed']) or bool(p['in_way'])
    msg = (f'Updated {p["branch"]} to {p["upstream"]} ({after[:7]})' if before != after else
           f'{p["branch"]} is at {p["upstream"]} ({after[:7]})') + (' · ' + ' · '.join(notes) if notes else '')
    unit = restart() if code_changed and restart_after and p['can_restart'] else None
    return {'message': msg, 'plan': p, 'changed': code_changed, 'restart': unit}


def _chown_tree(path, top):
    """Files the panel (root) wrote into the git dir belong to the repo owner (git_ops reports foreign files)."""
    if os.geteuid() != 0 or not os.path.isdir(path):
        return
    uid, gid = git_ops._owner(top)
    for base, dirs, files in os.walk(path):
        for n in [base] + [os.path.join(base, x) for x in dirs + files]:
            try:
                os.lchown(n, uid, gid)
            except OSError:
                pass


def restart():
    """Restart the panel's own unit shortly after the response is sent. Returns the unit name."""
    unit = own_unit()
    if not unit:
        raise GitError('The panel is not running as a systemd service — restart it by hand', 409)
    cmd = ['systemctl', '--no-block', 'restart', unit]
    if os.geteuid() != 0:
        cmd = ['sudo', '-n'] + cmd
    threading.Timer(0.8, lambda: subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)).start()
    return unit


def _reset_for_tests():
    with _lock:
        _state.update(checked=0.0, checking=False, online=None, behind=0, ahead=0, commits=[], error='')
