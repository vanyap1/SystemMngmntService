"""SMB (CIFS) share for system images: mount / unmount / browse (HW Utils -> Clone / Image).

The share is mounted at ``MOUNT_POINT`` with the mount(2) system call (ctypes) — no cifs-utils needed, and the
password never appears on a command line. The kernel needs the server address (``ip=``); host names are resolved
here. The login can be remembered in core/credentials.py (outside every repository, mode 0600); the browser only
ever gets ``credentials.smb_public()``.
"""
import ctypes
import errno
import os
import re
import socket
import stat
import subprocess
import time

from core import credentials

MOUNT_POINT = '/mnt/smms-share'
VERSIONS = ['', '3.1.1', '3.0', '2.1', '2.0', '1.0']          # '' = negotiate
MAX_ENTRIES = 3000
_HOST = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$')
_SHARE = re.compile(r'^[^/\\:*?"<>|,]{1,80}$')
_FOLDER = re.compile(r'^[^/\\\x00]{1,120}$')
MS_NOSUID, MS_NODEV = 2, 4


class SmbError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def parse_share(text):
    """'smb://host/share/sub', '//host/share', '\\\\host\\share' -> (host, share, sub)."""
    s = (text or '').strip().replace('\\', '/')
    s = re.sub(r'^smb:', '', s, flags=re.I)
    s = s.lstrip('/')
    parts = [p for p in s.split('/') if p]
    if len(parts) < 2:
        raise SmbError('Share must look like //server/share (or smb://server/share)')
    host, share, sub = parts[0], parts[1], '/'.join(parts[2:])
    if not _HOST.match(host):
        raise SmbError(f'Invalid server name: {host}')
    if not _SHARE.match(share):
        raise SmbError(f'Invalid share name: {share}')
    if any(p in ('.', '..') for p in parts[2:]):
        raise SmbError('Invalid folder in the share path')
    return host, share, sub


def unc(host, share, sub=''):
    return f'//{host}/{share}' + (f'/{sub}' if sub else '')


def _opt(v):
    """Kernel cifs option value: commas are doubled (the only escape the parser knows)."""
    return str(v).replace(',', ',,')


def build_options(host, ip, share, username, password, vers, domain=''):
    if any(c in (username or '') + (domain or '') for c in ',='):
        raise SmbError('User name must not contain "," or "="')
    if vers not in VERSIONS:
        raise SmbError(f'Unknown SMB version: {vers}')
    opts = [f'ip={ip}', f'unc=\\\\{host}\\{share}', f'username={username or "guest"}',
            f'pass={_opt(password or "")}', 'uid=0', 'gid=0', 'file_mode=0644', 'dir_mode=0755',
            'noserverino', 'nounix', 'actimeo=1']
    if domain:
        opts.append(f'domain={domain}')
    if vers:
        opts.append(f'vers={vers}')
    if not password:
        opts.append('guest')
    return ','.join(opts)


def _mounts():
    try:
        with open('/proc/mounts', encoding='utf-8') as f:
            return [ln.split() for ln in f]
    except OSError:
        return []


def status():
    """{'mounted', 'source', 'mount_point', 'free', 'total', 'settings'}."""
    src = ''
    for m in _mounts():
        if len(m) > 2 and m[1] == MOUNT_POINT:
            src = m[0].replace('\\040', ' ')
    out = {'mounted': bool(src), 'source': src, 'mount_point': MOUNT_POINT, 'free': None, 'total': None,
           'root': os.geteuid() == 0, 'settings': credentials.smb_public(), 'versions': VERSIONS}
    if src:
        try:
            st = os.statvfs(MOUNT_POINT)
            out['free'], out['total'] = st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize
        except OSError:
            pass
    return out


_ERRORS = {
    errno.EACCES: 'access denied — wrong user name or password',
    errno.EPERM: 'access denied — wrong user name or password',
    errno.ENOENT: 'share not found on the server',
    errno.EHOSTDOWN: 'server is not reachable',
    errno.EHOSTUNREACH: 'server is not reachable',
    errno.ENETUNREACH: 'network is not reachable',
    errno.ECONNREFUSED: 'server refused the connection (no SMB service?)',
    errno.ETIMEDOUT: 'server did not answer (timeout)',
    errno.EOPNOTSUPP: 'SMB version not supported by the server — pick another one',
    errno.EINVAL: 'invalid mount options (try another SMB version)',
    errno.ENODEV: 'the kernel has no cifs support (module cifs)',
    errno.EBUSY: 'mount point is busy',
}


def _sys_mount(source, target, fstype, data):
    libc = ctypes.CDLL('libc.so.6', use_errno=True)
    rc = libc.mount(source.encode(), target.encode(), fstype.encode(), MS_NOSUID | MS_NODEV, data.encode())
    if rc != 0:
        e = ctypes.get_errno()
        raise SmbError(f'Mount failed: {_ERRORS.get(e, os.strerror(e))}', 502)


def mount(share, username='', password=None, vers='', remember=False):
    """Mount the share (``password=None`` = the remembered one). Remembers share / user / version always."""
    if os.geteuid() != 0:
        raise SmbError('The panel runs without root: mounting is not possible here', 403)
    host, name, sub = parse_share(share)
    saved = credentials.smb()
    if password is None:
        password = saved['password'] if saved['share'] == share.strip() or not saved['share'] else ''
    if status()['mounted']:
        umount()
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        raise SmbError(f'Server name not found: {host}', 502)
    os.makedirs(MOUNT_POINT, mode=0o700, exist_ok=True)
    _sys_mount(unc(host, name), MOUNT_POINT, 'cifs', build_options(host, ip, name, username, password, vers))
    credentials.set_smb(share=share.strip(), username=username or '', vers=vers or '',
                        password=password if remember else '')
    st = status()
    st['sub'] = sub
    return st


def umount():
    if not status()['mounted']:
        return status()
    r = subprocess.run(['umount', MOUNT_POINT], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        if 'busy' in msg:
            msg = 'the share is in use (an image is being written?)'
        raise SmbError(f'Unmount failed: {msg}', 409)
    return status()


def forget():
    credentials.set_smb(password='')
    return status()


def _require_mounted():
    if not status()['mounted']:
        raise SmbError('The share is not mounted', 409)


def path_of(rel):
    """Absolute path of ``rel`` inside the mounted share (validated)."""
    _require_mounted()
    rel = (rel or '').strip().strip('/')
    if '\x00' in rel or any(p == '..' for p in rel.split('/')):
        raise SmbError('Invalid path')
    root = os.path.realpath(MOUNT_POINT)
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):     # symlinks must not lead out of the share
        raise SmbError('Invalid path')
    return full


def _mode(st):
    return stat.filemode(st.st_mode)


def listdir(rel=''):
    """Entries of a folder in the share: dirs first, symlinks are shown, not followed."""
    full = path_of(rel)
    if not os.path.isdir(full):
        raise SmbError('Not a folder', 404)
    items = []
    try:
        with os.scandir(full) as it:
            for e in it:
                if len(items) >= MAX_ENTRIES:
                    break
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                kind = 'link' if stat.S_ISLNK(st.st_mode) else 'dir' if stat.S_ISDIR(st.st_mode) else 'file'
                item = {'name': e.name, 'type': kind, 'size': st.st_size if kind == 'file' else None,
                        'mtime': st.st_mtime, 'mode': _mode(st)}
                if kind == 'link':
                    try:
                        item['target'] = os.readlink(e.path)
                    except OSError:
                        item['target'] = '?'
                items.append(item)
    except PermissionError:
        raise SmbError('Permission denied', 403)
    except OSError as e:
        raise SmbError(f'Cannot read the folder: {e.strerror}', 502)
    items.sort(key=lambda i: (i['type'] != 'dir', i['name'].lower()))
    rel = os.path.relpath(full, MOUNT_POINT)
    rel = '' if rel == '.' else rel
    return {'path': rel, 'items': items, 'truncated': len(items) >= MAX_ENTRIES, 'time': time.time()}


def mkdir(rel, name):
    if not _FOLDER.match(name or '') or name in ('.', '..'):
        raise SmbError('Invalid folder name')
    full = os.path.join(path_of(rel), name)
    if os.path.exists(full):
        raise SmbError('Already exists', 409)
    try:
        os.mkdir(full)
    except OSError as e:
        raise SmbError(f'Cannot create the folder: {e.strerror}', 502)
    return listdir(rel)
