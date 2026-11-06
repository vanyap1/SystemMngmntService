"""Git for the panel's repositories (target_dir, the panel itself, help_dir): status, commit, branches,
push/pull, problem detection with fixes.

Safety rules:
- git runs as the **owner of the repository** (the live panel runs as root; root-owned files in .git would break
  the owner's own git, and git refuses "dubious ownership").
- The HTTPS token (core/credentials.py) is given to git only through a one-shot credential helper that reads an
  environment variable of that single process: it is never written to .git/config, a remote URL or a file in a repo,
  and every output is scrubbed of it.
- Paths from the client must be in the current status list; refs are validated with ``git check-ref-format``;
  ``--`` always separates paths from options.
"""
import os
import pwd
import re
import shutil
import subprocess
import threading
import time

from core import config, credentials

GIT = shutil.which('git') or '/usr/bin/git'
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
TRACKED_SECRETS = ('.secret_key',)            # files that must never be tracked
_CRED_IN_URL = re.compile(r'^(https?://)([^/@\s]+)@', re.I)


class GitError(Exception):
    def __init__(self, msg, status=400, output=''):
        super().__init__(msg)
        self.status = status
        self.output = output


# ── Repositories ────────────────────────────────────────────────

def repo_sources():
    return [('project', 'Project (target_dir)', config.target_dir()),
            ('panel', 'Panel (SystemMngmntService)', config.BASE_DIR),
            ('help', 'Docs (help_dir)', config.help_dir())]


def _owner(path):
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    st = os.stat(p or '/')
    return st.st_uid, st.st_gid


def _run_raw(cwd, args, timeout=30, env_extra=None, token=None, input_text=None):
    """Run git in ``cwd`` as the owner of ``cwd``; returns (rc, stdout, stderr) with the token scrubbed."""
    uid, gid = _owner(cwd)
    try:
        home = pwd.getpwuid(uid).pw_dir
    except KeyError:
        home = '/tmp'
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': home, 'LC_ALL': 'C', 'LANG': 'C',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false', 'SSH_ASKPASS': '/bin/false',
           'GIT_SSH_COMMAND': 'ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15',
           'GIT_EDITOR': 'true', 'GIT_MERGE_AUTOEDIT': 'no'}
    if env_extra:
        env.update(env_extra)
    pre = []
    if token:
        # One-shot helper: the secret lives only in this process' environment.
        env['SMMS_GIT_USER'] = token[0] or 'git'
        env['SMMS_GIT_TOKEN'] = token[1]
        pre = ['-c', 'credential.helper=',
               '-c', 'credential.helper=!f() { test "$1" = get && echo "username=$SMMS_GIT_USER" && echo "password=$SMMS_GIT_TOKEN"; }; f']
    kw = {}
    if os.geteuid() == 0 and uid != 0:
        kw = {'user': uid, 'group': gid, 'extra_groups': []}
    try:
        r = subprocess.run([GIT, *pre, *args], cwd=cwd, env=env, capture_output=True, text=True,
                           timeout=timeout, input=input_text, **kw)
        out, err, rc = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        out, err, rc = '', f'Timeout ({timeout} s)', -1
    except OSError as e:
        out, err, rc = '', str(e), -1
    return rc, scrub(out), scrub(err)


def scrub(text):
    """Remove the stored token and credentials embedded in URLs from any text shown to the user."""
    if not text:
        return text
    tok = credentials.git()['token']
    if tok:
        text = text.replace(tok, '***')
    return re.sub(r'(https?://)[^/@\s:]+:[^/@\s]+@', r'\1***@', text)


SCAN_SKIP = {'node_modules', '__pycache__', 'venv', '.venv', 'env', 'build', 'dist', 'site-packages'}
SCAN_DEPTH, SCAN_LIMIT = 3, 40


def _toplevel(path):
    rc, out, _ = _run_raw(path, ['rev-parse', '--show-toplevel'], timeout=10)
    return out.strip() if rc == 0 else None


SCAN_SECONDS, SCAN_CACHE = 1.5, 20      # time budget of one scan; reuse its result for this long
_scan_cache = {}


def scan_target(fresh=False):
    """Git worktrees inside target_dir (e.g. projects cloned from GitHub): [abs top], at most SCAN_LIMIT.
    Stays on target_dir's filesystem (a big disk mounted under it is not walked), stops after SCAN_SECONDS,
    and the result is cached for SCAN_CACHE seconds (clone/init pass ``fresh``)."""
    root = os.path.realpath(config.target_dir())
    hit = _scan_cache.get(root)
    if hit and not fresh and time.monotonic() - hit[0] < SCAN_CACHE:
        return list(hit[1])
    found = []
    if not os.path.isdir(root):
        return found
    dev = os.stat(root).st_dev
    deadline = time.monotonic() + SCAN_SECONDS

    def same_fs(path):
        try:
            return os.lstat(path).st_dev == dev and not os.path.islink(path)
        except OSError:
            return False
    for dirpath, dirs, files in os.walk(root):
        depth = os.path.relpath(dirpath, root).count(os.sep) + (dirpath != root)
        if dirpath != root and ('.git' in dirs or '.git' in files):
            found.append(dirpath)
            if len(found) >= SCAN_LIMIT:
                break
        if time.monotonic() > deadline:
            break
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in SCAN_SKIP and depth < SCAN_DEPTH
                         and same_fs(os.path.join(dirpath, d)))
    _scan_cache[root] = (time.monotonic(), list(found))
    return found


def _dir_id(top):
    return 'dir:' + os.path.relpath(top, os.path.realpath(config.target_dir()))


def resolve(repo_id):
    """Repository id -> {'id', 'label', 'path', 'top'}; ``top`` is None when the folder is not in a git repo.
    Ids: project / panel / help, or ``dir:<path relative to target_dir>`` for a repository inside target_dir."""
    if isinstance(repo_id, str) and repo_id.startswith('dir:'):
        root = os.path.realpath(config.target_dir())
        rel = repo_id[4:]
        full = os.path.realpath(os.path.join(root, rel))
        if not rel or rel.startswith('/') or not full.startswith(root + os.sep) or \
                not os.path.exists(os.path.join(full, '.git')):
            raise GitError('Unknown repository', 404)
        return {'id': repo_id, 'label': os.path.relpath(full, root) + ' (in target_dir)', 'path': full, 'top': full}
    for rid, label, path in repo_sources():
        if rid == repo_id:
            top = _toplevel(path) if os.path.isdir(path) else None
            return {'id': rid, 'label': label, 'path': path, 'top': top}
    raise GitError('Unknown repository', 404)


def repos():
    """Known repositories; ids sharing one worktree are merged (labels joined)."""
    out, seen = [], {}
    for rid, _, _ in repo_sources():
        r = resolve(rid)
        key = r['top'] or ('nogit:' + r['path'])
        if key in seen:
            seen[key]['label'] += ' · ' + r['label']
            seen[key]['aliases'].append(rid)
            continue
        r['aliases'] = [rid]
        seen[key] = r
        out.append(r)
    for top in scan_target():
        if top in seen:
            continue
        r = resolve(_dir_id(top))
        r['aliases'] = [r['id']]
        seen[top] = r
        out.append(r)
    return out


def remote_info(url):
    """Hosting info of a remote URL: {'host', 'slug', 'web'} (web = browser URL, without credentials)."""
    url = scrub(url or '')
    m = re.match(r'^(?:[\w+]+://)?(?:[^@/]+@)?([^/:]+)[:/](?:\d+/)?(.+?)(?:\.git)?/?$', url)
    if not m or url.startswith(('/', 'file:')):
        return {'host': '', 'slug': url, 'web': ''}
    host, slug = m.group(1), m.group(2)
    return {'host': host, 'slug': slug, 'web': f'https://{host}/{slug}' if '.' in host else ''}


def tree_status():
    """Changed files of every repository the code editor shows (target_dir's repo + repos inside it)."""
    root = os.path.realpath(config.target_dir())
    tops = []
    t = _toplevel(root) if os.path.isdir(root) else None
    if t:
        tops.append(('project', t))
    tops += [(_dir_id(x), x) for x in scan_target() if x != t]
    repos_out, files = [], {}
    for rid, top in tops:
        try:
            r = Repo(rid)
            st = r.status()
        except GitError:
            continue
        remotes = r.remotes()
        origin = next((x for x in remotes if x['name'] == 'origin'), remotes[0] if remotes else None)
        repos_out.append({'id': rid, 'top': top, 'branch': st['branch'], 'ahead': st['ahead'], 'behind': st['behind'],
                          'changes': len(st['files']), 'remote': remote_info(origin['url']) if origin else None})
        for f in st['files']:
            files[os.path.join(top, f['path'])] = f['kind']
    return {'root': root, 'repos': repos_out, 'files': files}


_CLONE_URL = re.compile(r'^(https?://[^\s]+|ssh://[^\s]+|[\w.-]+@[\w.-]+:[^\s]+|file://[^\s]+)$')


def clone(url, name):
    """Clone ``url`` into target_dir/<name> (as the owner of target_dir; the token is used for https)."""
    url = (url or '').strip()
    if not _CLONE_URL.match(url) or url.startswith('-'):
        raise GitError('Enter an https://, ssh:// or git@host:owner/repo URL')
    if _CRED_IN_URL.match(url):
        raise GitError('Do not put credentials into the URL — set the token in Settings → Git')
    name = (name or '').strip() or re.sub(r'\.git$', '', url.rstrip('/').rsplit('/', 1)[-1].rsplit(':', 1)[-1])
    if not re.match(r'^[\w][\w.-]{0,79}$', name):
        raise GitError(f'Invalid folder name: "{name}"')
    root = config.target_dir()
    dest = os.path.join(root, name)
    if os.path.exists(dest):
        raise GitError(f'{dest} already exists', 409)
    c = credentials.git()
    token = (c['username'], c['token']) if c['token'] and url.startswith('https://') else None
    rc, out, err = _run_raw(root, ['clone', '--', url, name], timeout=600, token=token)
    if rc != 0:
        raise GitError((err or out).strip().splitlines()[-1] if (err or out).strip() else 'clone failed', 400, (out + err).strip())
    _scan_cache.clear()
    return {'repo': _dir_id(os.path.realpath(dest)), 'path': dest}


def init_target():
    root = config.target_dir()
    if _toplevel(root):
        raise GitError('target_dir is already inside a git repository', 409)
    rc, out, err = _run_raw(root, ['init', '-q'], timeout=30)
    if rc != 0:
        raise GitError(err.strip() or 'git init failed')
    _scan_cache.clear()
    return {'repo': 'project', 'path': root}


def _lock(top):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(top, threading.Lock())


class Repo:
    def __init__(self, repo_id):
        r = resolve(repo_id)
        if not r['top']:
            raise GitError(f'{r["path"]} is not inside a git repository', 409)
        self.id, self.label, self.top = r['id'], r['label'], r['top']

    def run(self, *args, timeout=30, check=True, network=False, input_text=None):
        token = None
        if network:
            c = credentials.git()
            if c['token']:
                token = (c['username'], c['token'])
        rc, out, err = _run_raw(self.top, list(args), timeout=timeout, token=token, input_text=input_text)
        if check and rc != 0:
            raise GitError((err or out).strip().splitlines()[-1] if (err or out).strip() else f'git {args[0]} failed',
                           400, (out + err).strip())
        return out if not check else out

    def ok(self, *args, timeout=15):
        rc, _, _ = _run_raw(self.top, list(args), timeout=timeout)
        return rc == 0

    def cfg(self, key, scope=None):
        args = ['config'] + ([f'--{scope}'] if scope else []) + ['--get', key]
        rc, out, _ = _run_raw(self.top, args, timeout=10)
        return out.strip() if rc == 0 else ''

    def git_dir(self):
        p = self.run('rev-parse', '--git-dir').strip()
        return p if os.path.isabs(p) else os.path.join(self.top, p)

    # ── Status ──────────────────────────────────────────────

    def status(self):
        out = self.run('status', '--porcelain=v2', '--branch', '-z', '--untracked-files=all')
        info = {'branch': None, 'oid': None, 'upstream': None, 'ahead': 0, 'behind': 0, 'files': []}
        parts = out.split('\0')
        i = 0
        while i < len(parts):
            rec = parts[i]
            i += 1
            if not rec:
                continue
            if rec.startswith('# '):
                k, _, v = rec[2:].partition(' ')
                if k == 'branch.head':
                    info['branch'] = None if v == '(detached)' else v
                elif k == 'branch.oid':
                    info['oid'] = None if v == '(initial)' else v
                elif k == 'branch.upstream':
                    info['upstream'] = v
                elif k == 'branch.ab':
                    a, b = v.split()
                    info['ahead'], info['behind'] = int(a), -int(b)
                continue
            t = rec[0]
            if t == '1':
                f = rec.split(' ', 8)
                info['files'].append(self._file(f[1], f[8]))
            elif t == '2':
                f = rec.split(' ', 9)
                orig = parts[i]
                i += 1
                e = self._file(f[1], f[9])
                e['orig'] = orig
                info['files'].append(e)
            elif t == 'u':
                f = rec.split(' ', 10)
                info['files'].append({'path': f[10], 'x': 'U', 'y': 'U', 'staged': False, 'unstaged': True, 'conflict': True, 'kind': 'conflict'})
            elif t == '?':
                info['files'].append({'path': rec[2:], 'x': '?', 'y': '?', 'staged': False, 'unstaged': True, 'kind': 'untracked'})
        info['files'].sort(key=lambda f: f['path'])
        return info

    @staticmethod
    def _file(xy, path):
        x, y = xy[0], xy[1]
        kind = {'A': 'added', 'D': 'deleted', 'R': 'renamed', 'C': 'copied', 'M': 'modified', 'T': 'modified'}
        k = kind.get(x if x != '.' else y, 'modified')
        return {'path': path, 'x': x, 'y': y, 'staged': x != '.', 'unstaged': y != '.', 'kind': k}

    def branches(self):
        out = self.run('for-each-ref', '--format=%(refname:short)%1f%(upstream:short)%1f%(upstream:track)%1f%(committerdate:relative)%1f%(HEAD)',
                       'refs/heads')
        res = []
        for line in out.splitlines():
            name, up, track, date, head = (line.split('\x1f') + [''] * 5)[:5]
            res.append({'name': name, 'upstream': up, 'track': track.strip('[]'), 'date': date, 'current': head == '*'})
        return res

    def remotes(self):
        res = {}
        for line in self.run('remote', '-v').splitlines():
            name, url = line.split()[:2]
            res[name] = scrub(url)
        return [{'name': n, 'url': u} for n, u in res.items()]

    def log(self, n=15, rev=None):
        """Recent commits of HEAD, or of ``rev`` (an internal revision range such as 'HEAD..@{u}', never client input)."""
        if not self.ok('rev-parse', '--verify', '-q', 'HEAD'):
            return []
        out = self.run('log', f'-n{n}', '--pretty=format:%H%x1f%h%x1f%an%x1f%ar%x1f%s%x1f%D%x1e', *([rev] if rev else []))
        res = []
        for rec in out.split('\x1e'):
            rec = rec.strip('\n')
            if not rec:
                continue
            h, short, author, when, subject, refs = (rec.split('\x1f') + [''] * 6)[:6]
            res.append({'hash': h, 'short': short, 'author': author, 'when': when, 'subject': subject, 'refs': refs})
        return res

    def identity(self):
        return {'name': self.cfg('user.name'), 'email': self.cfg('user.email'),
                'local_name': self.cfg('user.name', 'local'), 'local_email': self.cfg('user.email', 'local'),
                'global_name': self.cfg('user.name', 'global'), 'global_email': self.cfg('user.email', 'global')}

    def overview(self):
        st = self.status()
        remotes = self.remotes()
        origin = next((x for x in remotes if x['name'] == 'origin'), remotes[0] if remotes else None)
        return {'repo': {'id': self.id, 'label': self.label, 'top': self.top,
                         'remote': remote_info(origin['url']) if origin else None}, 'status': st,
                'branches': self.branches(), 'remotes': self.remotes(), 'log': self.log(),
                'identity': self.identity(), 'problems': self.problems(st), 'credentials': credentials.public()}

    # ── Validation ──────────────────────────────────────────

    def check_branch(self, name):
        name = (name or '').strip()
        if not name or name.startswith('-') or not self.ok('check-ref-format', '--branch', name):
            raise GitError(f'Invalid branch name: "{name}"')
        return name

    def check_paths(self, paths, st=None):
        st = st or self.status()
        known = {f['path'] for f in st['files']} | {f.get('orig') for f in st['files'] if f.get('orig')}
        bad = [p for p in paths if p not in known]
        if bad:
            raise GitError('Not a changed file: ' + ', '.join(bad[:3]))
        return paths

    # ── Actions ─────────────────────────────────────────────

    def diff(self, path):
        st = self.status()
        self.check_paths([path], st)
        f = next(x for x in st['files'] if x['path'] == path or x.get('orig') == path)
        if f['kind'] == 'untracked':
            full = os.path.join(self.top, path)
            try:
                with open(full, 'rb') as fh:
                    data = fh.read(200_000)
                if b'\0' in data:
                    return '(binary file)'
                return ''.join('+' + ln + '\n' for ln in data.decode('utf-8', 'replace').splitlines())
            except OSError as e:
                return f'({e})'
        out = self.run('diff', '--no-color', '--no-ext-diff', 'HEAD', '--', path) if st['oid'] else \
            self.run('diff', '--no-color', '--cached', '--', path)
        return out[:200_000] or '(no textual changes)'

    def commit(self, message, paths=None, new_branch=None, amend=False):
        message = (message or '').strip()
        if not message:
            raise GitError('Commit message is empty')
        with _lock(self.top):
            st = self.status()
            if any(f.get('conflict') for f in st['files']):
                raise GitError('Resolve the conflicts first (see Problems)', 409)
            ident = self.identity()
            if not ident['name'] or not ident['email']:
                raise GitError('Set the git user name and e-mail first', 409)
            if new_branch:
                self.run('switch', '-c', self.check_branch(new_branch))
            if paths is None:
                self.run('add', '-A')
            else:
                if not paths:
                    raise GitError('No files selected')
                self.check_paths(paths, st)
                origs = [f['orig'] for f in st['files'] if f.get('orig') and f['path'] in paths]   # renames: old path too
                self.run('reset', '-q', '--', '.') if st['oid'] else None
                self.run('add', '-A', '--', *paths, *origs)
            if not self.ok('diff', '--cached', '--quiet') or amend:
                self.run('commit', '-q', '-F', '-', *(['--amend'] if amend else []), input_text=message + '\n')
            else:
                raise GitError('Nothing to commit')
            return self.run('log', '-1', '--pretty=format:%h %s').strip()

    def create_branch(self, name, checkout=True):
        name = self.check_branch(name)
        with _lock(self.top):
            self.run('switch', '-c', name) if checkout else self.run('branch', name)
        return name

    def checkout(self, name):
        name = self.check_branch(name)
        with _lock(self.top):
            self.run('switch', name)
        return name

    def delete_branch(self, name, force=False):
        name = self.check_branch(name)
        with _lock(self.top):
            self.run('branch', '-D' if force else '-d', name)
        return name

    def fetch(self):
        with _lock(self.top):
            return self.run('fetch', '--prune', timeout=120, network=True) or 'fetched'

    def pull(self, mode='ff'):
        flag = {'ff': '--ff-only', 'rebase': '--rebase', 'merge': '--no-rebase'}.get(mode)
        if not flag:
            raise GitError('Bad pull mode')
        with _lock(self.top):
            rc, out, err = _run_raw(self.top, ['pull', flag], timeout=180, token=self._token())
            if rc != 0:
                raise GitError((err or out).strip().splitlines()[-1] if (err or out).strip() else 'pull failed', 400, (out + err).strip())
            return (out + err).strip()

    def push(self, force_lease=False):
        with _lock(self.top):
            st = self.status()
            if not st['branch']:
                raise GitError('Detached HEAD: create a branch first', 409)
            args = ['push', '--porcelain']
            if force_lease:
                args.append('--force-with-lease')
            if not st['upstream']:
                remotes = [r['name'] for r in self.remotes()]
                if not remotes:
                    raise GitError('No remote configured', 409)
                args += ['-u', 'origin' if 'origin' in remotes else remotes[0], st['branch']]
            rc, out, err = _run_raw(self.top, args, timeout=180, token=self._token())
            if rc != 0:
                raise GitError((err or out).strip().splitlines()[-1] if (err or out).strip() else 'push failed', 400, (out + err).strip())
            return (out + err).strip()

    def _token(self):
        c = credentials.git()
        return (c['username'], c['token']) if c['token'] else None

    def discard(self, paths):
        with _lock(self.top):
            st = self.status()
            self.check_paths(paths, st)
            files = {f['path']: f for f in st['files']}
            untracked = [p for p in paths if files.get(p, {}).get('kind') == 'untracked']
            tracked = [p for p in paths if p not in untracked]
            if tracked:
                self.run('restore', '--staged', '--worktree', '--source=HEAD', '--', *tracked) if st['oid'] else \
                    self.run('rm', '-q', '--cached', '--', *tracked)
            for p in untracked:
                self.run('clean', '-f', '-q', '--', p)
        return len(paths)

    def backup(self):
        """Safety net before destructive actions: a backup branch at HEAD + a stash of uncommitted work."""
        stamp = time.strftime('%Y%m%d-%H%M%S')
        name = None
        if self.ok('rev-parse', '--verify', '-q', 'HEAD'):
            name = f'backup/{stamp}'
            self.run('branch', name)
        stashed = False
        if self.status()['files']:
            self.run('stash', 'push', '-u', '-q', '-m', f'panel backup {stamp}')
            stashed = True
        return name, stashed

    def reset_to_upstream(self):
        with _lock(self.top):
            st = self.status()
            if not st['upstream']:
                raise GitError('The branch has no upstream', 409)
            name, stashed = self.backup()
            self.run('reset', '--hard', '-q', st['upstream'])
            return f'Reset to {st["upstream"]}. Backup branch: {name}' + ('; uncommitted changes stashed' if stashed else '')

    def set_identity(self, name, email, scope='local'):
        if scope not in ('local', 'global'):
            raise GitError('Bad scope')
        name, email = (name or '').strip(), (email or '').strip()
        if not name or not re.match(r'^[^@\s]+@[^@\s]+$', email):
            raise GitError('Enter a name and a valid e-mail')
        self.run('config', f'--{scope}', 'user.name', name)
        self.run('config', f'--{scope}', 'user.email', email)

    # ── Problems ────────────────────────────────────────────

    def problems(self, st=None):
        st = st or self.status()
        gd = self.git_dir()
        out = []

        def add(pid, level, title, detail='', fixes=()):
            out.append({'id': pid, 'level': level, 'title': title, 'detail': detail,
                        'fixes': [{'id': f[0], 'label': f[1], 'danger': len(f) > 2 and f[2]} for f in fixes]})

        uid, _ = _owner(self.top)
        foreign = self._foreign_files(gd, uid)
        if foreign:
            add('ownership', 'error', f'{foreign} file(s) in .git are not owned by the repository owner',
                'Usually left by git running as root. The owner\'s git (SSH, IDE) fails on them.',
                [('chown_git', 'Give them back to the owner')] if os.geteuid() == 0 else ())
        if os.path.exists(os.path.join(gd, 'index.lock')) and time.time() - os.path.getmtime(os.path.join(gd, 'index.lock')) > 60:
            add('index_lock', 'error', 'Stale index.lock', 'A crashed git process left .git/index.lock; every write fails.',
                [('remove_lock', 'Remove index.lock')])
        if os.path.exists(os.path.join(gd, 'MERGE_HEAD')):
            add('merge', 'error', 'A merge is in progress', 'Finish it (resolve, then commit) or abort it.',
                [('merge_abort', 'Abort the merge', True)])
        if os.path.isdir(os.path.join(gd, 'rebase-merge')) or os.path.isdir(os.path.join(gd, 'rebase-apply')):
            add('rebase', 'error', 'A rebase is in progress', 'Resolve and continue in a terminal, or abort it.',
                [('rebase_abort', 'Abort the rebase', True)])
        conflicts = [f['path'] for f in st['files'] if f.get('conflict')]
        if conflicts:
            add('conflicts', 'error', f'{len(conflicts)} file(s) with merge conflicts', ', '.join(conflicts[:5]))
        ident = self.identity()
        if not ident['name'] or not ident['email']:
            add('identity', 'warn', 'Git user name / e-mail are not set', 'Commits need them — set them below.')
        if not st['branch']:
            add('detached', 'warn', 'Detached HEAD', 'Commits made here belong to no branch.',
                [('branch_here', 'Create a branch here')])
        remotes = self.remotes()
        if not remotes:
            add('no_remote', 'info', 'No remote', 'Push / pull need a remote (git remote add origin <url>).')
        if st['branch'] and remotes and not st['upstream']:
            add('no_upstream', 'info', f'Branch "{st["branch"]}" has no upstream', 'The first Push sets it.')
        if st['ahead'] and st['behind']:
            add('diverged', 'warn', f'Diverged from {st["upstream"]}: {st["ahead"]} ahead, {st["behind"]} behind',
                'Pull with rebase (linear history) or merge; or reset to the remote (local commits are kept in a backup branch).',
                [('pull_rebase', 'Pull (rebase)'), ('pull_merge', 'Pull (merge)'), ('reset_upstream', 'Reset to remote', True)])
        elif st['behind']:
            add('behind', 'info', f'{st["behind"]} commit(s) behind {st["upstream"]}', '', [('pull_ff', 'Pull')])
        for r in self._raw_remotes():
            if _CRED_IN_URL.match(r['url']):
                add('url_credentials', 'error', f'Credentials are stored in the URL of remote "{r["name"]}"',
                    'Anyone who can read .git/config sees them. Remove them and use the token in Settings → Git.',
                    [('strip_url', 'Remove credentials from the URL')])
                break
        tracked = [p for p in TRACKED_SECRETS if self.ok('ls-files', '--error-unmatch', '--', p)]
        if tracked:
            add('tracked_secret', 'error', 'Secret file tracked by git: ' + ', '.join(tracked),
                'It would be pushed to the remote.', [('untrack_secret', 'Stop tracking (keep the file)')])
        tok = credentials.git()['token']
        if tok:
            rc, hits, _ = _run_raw(self.top, ['grep', '-l', '-F', '-e', tok, '--'], timeout=20)
            rc2, hits2, _ = _run_raw(self.top, ['grep', '--cached', '-l', '-F', '-e', tok, '--'], timeout=20)
            files = sorted(set((hits + hits2).split()))
            if files:
                add('token_in_repo', 'error', 'The git token appears in tracked/staged files: ' + ', '.join(files[:5]),
                    'Remove it from these files before committing; if it was already pushed, revoke the token.')
        cpath = credentials.PATH
        if os.path.realpath(cpath).startswith(os.path.realpath(self.top) + os.sep) and \
                not self.ok('check-ignore', '-q', '--', os.path.relpath(cpath, self.top)):
            add('cred_file', 'error', 'The credentials file lies inside this repository and is not ignored', cpath,
                [('ignore_cred', 'Add it to .gitignore')])
        return out

    def _raw_remotes(self):
        rc, out, _ = _run_raw(self.top, ['config', '--get-regexp', r'^remote\..*\.url$'], timeout=10)
        res = []
        for line in out.splitlines() if rc == 0 else []:
            k, _, url = line.partition(' ')
            res.append({'name': k.split('.', 1)[1].rsplit('.', 1)[0], 'url': url})
        return res

    @staticmethod
    def _foreign_files(gd, uid, limit=5000):
        n = 0
        for dirpath, dirs, files in os.walk(gd):
            for name in dirs + files:
                try:
                    if os.lstat(os.path.join(dirpath, name)).st_uid != uid:
                        n += 1
                except OSError:
                    pass
            if n > limit:
                break
        return n

    def fix(self, pid):
        with _lock(self.top):
            gd = self.git_dir()
            if pid == 'chown_git':
                if os.geteuid() != 0:
                    raise GitError('Only possible when the panel runs as root', 409)
                uid, gid = _owner(self.top)
                for dirpath, dirs, files in os.walk(gd):
                    for name in [dirpath] + [os.path.join(dirpath, x) for x in dirs + files]:
                        try:
                            os.lchown(name, uid, gid)
                        except OSError:
                            pass
                return 'Ownership restored'
            if pid == 'remove_lock':
                os.remove(os.path.join(gd, 'index.lock'))
                return 'index.lock removed'
            if pid == 'merge_abort':
                self.run('merge', '--abort')
                return 'Merge aborted'
            if pid == 'rebase_abort':
                self.run('rebase', '--abort')
                return 'Rebase aborted'
            if pid == 'branch_here':
                name = 'rescue/' + time.strftime('%Y%m%d-%H%M%S')
                self.run('switch', '-c', name)
                return f'Created branch {name}'
            if pid == 'strip_url':
                for r in self._raw_remotes():
                    if _CRED_IN_URL.match(r['url']):
                        self.run('remote', 'set-url', r['name'], _CRED_IN_URL.sub(r'\1', r['url']))
                return 'Credentials removed from the remote URL'
            if pid == 'untrack_secret':
                for p in TRACKED_SECRETS:
                    if self.ok('ls-files', '--error-unmatch', '--', p):
                        self.run('rm', '-q', '--cached', '--', p)
                return 'Untracked (commit to record it)'
            if pid == 'ignore_cred':
                rel = os.path.relpath(credentials.PATH, self.top)
                with open(os.path.join(self.top, '.gitignore'), 'a', encoding='utf-8') as f:
                    f.write(f'\n# panel credentials (git token)\n/{rel}\n')
                return '.gitignore updated'
        # actions that take the lock themselves
        if pid == 'pull_rebase':
            return self.pull('rebase')
        if pid == 'pull_merge':
            return self.pull('merge')
        if pid == 'pull_ff':
            return self.pull('ff')
        if pid == 'reset_upstream':
            return self.reset_to_upstream()
        raise GitError('Unknown fix', 404)
