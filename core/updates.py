"""Update check of the panel itself (the git repository the panel runs from, id 'panel').

While the UI polls /api/update/status, a background thread runs `git fetch` of the upstream at most every
``update_check_minutes`` (sooner again after a failure, e.g. no internet) and reports the commits HEAD is behind.
Applying an update is `git pull --ff-only` through git_ops (as the repo owner, token via the credential helper);
the panel then restarts its own systemd unit on request. Nothing runs while nobody has the panel open.
"""
import os
import subprocess
import threading
import time

from core import config, git_ops
from core.git_ops import GitError

FETCH_TIMEOUT = 30
RETRY_MINUTES = 10          # after a failed fetch (offline) try again sooner than the interval
MAX_COMMITS = 20
BOOT = time.time()        # lets the UI see that a restarted panel answers

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
