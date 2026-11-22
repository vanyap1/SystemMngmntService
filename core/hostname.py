"""Settings → General → System host name: rename the machine the panel runs on.

``set_hostname`` changes the static host name (``hostnamectl set-hostname``; without systemd: /etc/hostname +
``hostname``), points the ``127.0.1.1`` line of /etc/hosts to the new name (else sudo complains "unable to resolve
host") and moves this host's section of config.json to the new name (``config.rename_host``) — the panel keys its
per-host settings by the host name, so they would otherwise be lost at the next start.
"""
import os
import re
import shutil
import socket
import subprocess

from core import config

HOSTS_PATH = '/etc/hosts'
HOSTNAME_PATH = '/etc/hostname'
NAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$')


class HostnameError(Exception):
    pass


def check(name):
    name = (name or '').strip() if isinstance(name, str) else ''
    if not NAME_RE.match(name) or name.isdigit():
        raise HostnameError('Host name: 1–63 letters, digits and "-" (not at the start or end), not only digits')
    return name


def _run(argv):
    if os.geteuid() != 0:
        argv = ['sudo', '-n', *argv]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostnameError(f'{argv[0]}: {exc}')
    if r.returncode:
        raise HostnameError((r.stderr or r.stdout).strip() or f'{" ".join(argv)} failed ({r.returncode})')


def info():
    pretty = ''
    if shutil.which('hostnamectl'):
        try:
            pretty = subprocess.run(['hostnamectl', '--pretty'], capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        with open(HOSTS_PATH, encoding='utf-8') as f:
            hosts_ok = any(re.match(r'^\s*127\.0\.1\.1\s', l) and socket.gethostname() in l.split()[1:]
                           for l in f.read().splitlines())
    except OSError:
        hosts_ok = None
    return {'hostname': socket.gethostname(), 'config_host': config.HOSTNAME, 'pretty': pretty, 'hosts_ok': hosts_ok,
            'has_section': config.host_section() is not None}


def _fix_hosts(old, new):
    """127.0.1.1 line → the new name (old names on it replaced, a missing line added). Returns True if written."""
    with open(HOSTS_PATH, encoding='utf-8') as f:
        lines = f.read().splitlines()
    done = False
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*127\.0\.1\.1\s+)(.*)$', line)
        if not m:
            continue
        names = [new if n in (old, new) else re.sub(rf'^{re.escape(old)}\.', new + '.', n)
                 for n in m.group(2).split('#')[0].split()]
        if new not in names:
            names.insert(0, new)
        lines[i] = m.group(1) + ' '.join(dict.fromkeys(names))
        done = True
    if not done:
        at = next((i + 1 for i, l in enumerate(lines) if re.match(r'^\s*127\.0\.0\.1\s', l)), 0)
        lines.insert(at, f'127.0.1.1\t{new}')
    text = '\n'.join(lines) + '\n'
    tmp = HOSTS_PATH + '.smms-tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, HOSTS_PATH)
    return True


def set_hostname(name):
    new = check(name)
    old = socket.gethostname()
    if new == old and new == config.HOSTNAME:
        return dict(info(), changed=False)
    if shutil.which('hostnamectl'):
        _run(['hostnamectl', 'set-hostname', new])
    else:
        with open(HOSTNAME_PATH, 'w', encoding='utf-8') as f:
            f.write(new + '\n')
        _run(['hostname', new])
    warn = ''
    try:
        _fix_hosts(old, new)
    except OSError as exc:
        warn = f'/etc/hosts not updated: {exc}'
    moved = config.rename_host(new)
    return dict(info(), changed=True, old=old, moved_section=moved, warning=warn)
