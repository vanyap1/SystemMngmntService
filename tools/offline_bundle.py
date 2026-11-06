#!/usr/bin/env python3
"""Build an offline installation bundle of SystemMngmntService's dependencies for a Debian/Armbian target.

Runs on any Debian-based machine with internet (no root, the system is not touched): apt works in a private
directory with the target's architecture, so a bundle for an Allwinner H3 (armhf) or H5 (arm64) board can be
built on an aarch64 or x86 PC.

    python3 tools/offline_bundle.py --arch armhf,arm64 --suite bookworm [--components core,git,gpio,devices]

Result per target, in --out (default setup_data/):
    <suite>-<arch>/debs/*.deb + Packages   local apt repository (closure of the selected packages)
    <suite>-<arch>/wheels/*.whl            Flask 3 and its pure-Python dependencies
    <suite>-<arch>/manifest.json           suite, arch, python, components, packages
    smms-offline-<suite>-<arch>.tar        the three above, to copy next to the project on the target

The target is assumed to have Debian's base system (Priority required/important); everything else the
selected packages need is downloaded. install.sh --offline installs it with apt from the local repository,
so packages already installed in the same or a newer version are skipped.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Debian packages per optional component (keep in sync with COMPONENTS in install.sh).
COMPONENTS = {
    'core':    ['python3', 'python3-markupsafe', 'python3-pip', 'sudo', 'iproute2', 'whiptail'],
    'git':     ['git'],
    'gpio':    ['python3-libgpiod', 'gpiod', 'python3-serial', 'python3-smbus'],
    'devices': ['usbutils', 'pciutils', 'i2c-tools', 'can-utils'],
    'video':   ['ffmpeg'],
}
DEFAULT_COMPONENTS = ['core', 'git', 'gpio', 'devices']
# Pure-Python wheels installed with pip (MarkupSafe, the only compiled dependency, comes from python3-markupsafe).
WHEELS = ['flask>=3', 'werkzeug', 'jinja2', 'itsdangerous', 'click', 'blinker']
ARCHES = ('armhf', 'arm64', 'amd64', 'i386', 'armel')
KEYRING = '/usr/share/keyrings/debian-archive-keyring.gpg'
MIRROR = 'http://deb.debian.org/debian'
SECURITY = 'http://security.debian.org/debian-security'


def log(msg):
    print(msg, flush=True)


def parse_packages(text):
    """Stanzas of a Debian Packages index as dicts (continuation lines are kept with their field)."""
    out = []
    for block in text.split('\n\n'):
        fields, key = {}, None
        for line in block.splitlines():
            if line[:1] in (' ', '\t') and key:
                fields[key] += '\n' + line
            elif ':' in line:
                key, _, val = line.partition(':')
                fields[key] = val.strip()
        if 'Package' in fields:
            out.append(fields)
    return out


def version_lt(a, b):
    """Debian version comparison (dpkg --compare-versions)."""
    try:
        import apt_pkg
        apt_pkg.init_system()
        return apt_pkg.version_compare(a, b) < 0
    except ImportError:
        return subprocess.run(['dpkg', '--compare-versions', a, 'lt', b]).returncode == 0


def base_status(stanzas):
    """A fake dpkg status: the base system every Debian install has (Essential + Priority required/important),
    each in its oldest indexed version (the release itself), so newer -updates/-security builds that the selected
    packages depend on end up in the bundle. Dependency fields are left out so apt never tries to "fix" them."""
    base = {}
    for f in stanzas:
        if f.get('Essential') == 'yes' or f.get('Priority') in ('required', 'important'):
            old = base.get(f['Package'])
            if not old or version_lt(f['Version'], old['Version']):
                base[f['Package']] = f
    out = []
    for f in base.values():
        s = [f"Package: {f['Package']}", 'Status: install ok installed',
             f"Architecture: {f['Architecture']}", f"Version: {f['Version']}"]
        s += [f'{k}: {f[k]}' for k in ('Multi-Arch', 'Provides', 'Essential') if k in f]
        out.append('\n'.join(s) + '\n')
    return '\n'.join(out)


def archive_name(f):
    """File name apt gives a downloaded package: <pkg>_<version, ':' quoted>_<arch>.deb."""
    return f"{f['Package']}_{f['Version'].replace(':', '%3a')}_{f['Architecture']}.deb"


def local_index(stanzas, debs):
    """Match downloaded files to their index stanzas. Returns ({downloaded name: index file name}, Packages text)
    for a flat `deb [trusted=yes] file:DIR ./` repository."""
    by_name = {archive_name(f): f for f in stanzas if f.get('Filename')}
    names, out = {}, []
    for name in sorted(debs):
        f = by_name.get(name)
        if not f:
            raise SystemExit(f'[ERROR] {name}: not found in the package index')
        names[name] = os.path.basename(f['Filename'])
        lines = [f'{k}: {v}' for k, v in f.items() if k not in ('Filename', 'Description-md5')]
        lines.insert(1, f'Filename: ./{names[name]}')
        out.append('\n'.join(lines) + '\n')
    return names, '\n'.join(out)


def python_version(stanzas):
    """'3.11' from the target's python3 package version ('3.11.2-1+b1')."""
    for f in stanzas:
        if f['Package'] == 'python3':
            m = re.match(r'(?:\d+:)?(\d+\.\d+)', f['Version'])
            if m:
                return m.group(1)
    raise SystemExit('[ERROR] python3 not found in the package index')


class AptTarget:
    """apt confined to a private directory, with the target's architecture and sources."""

    def __init__(self, work, suite, arch, mirror, keyring):
        self.work, self.suite, self.arch = work, suite, arch
        for d in ('lists/partial', 'archives/partial', 'etc/apt.conf.d', 'etc/preferences.d', 'dpkg'):
            os.makedirs(os.path.join(work, d), exist_ok=True)
        opt = f'[arch={arch} signed-by={keyring}]'
        with open(self.p('etc/sources.list'), 'w') as fh:
            fh.write(f'deb {opt} {mirror} {suite} main\n'
                     f'deb {opt} {mirror} {suite}-updates main\n'
                     f'deb {opt} {SECURITY} {suite}-security main\n')
        if not os.path.exists(self.p('dpkg/status')):
            open(self.p('dpkg/status'), 'w').close()

    def p(self, rel):
        return os.path.join(self.work, rel)

    def opts(self):
        o = {
            'Dir::Etc::SourceList': self.p('etc/sources.list'), 'Dir::Etc::SourceParts': '/dev/null',
            'Dir::Etc::Parts': self.p('etc/apt.conf.d'), 'Dir::Etc::PreferencesParts': self.p('etc/preferences.d'),
            'Dir::State::Lists': self.p('lists'), 'Dir::State::status': self.p('dpkg/status'),
            'Dir::Cache': self.work, 'Dir::Cache::archives': self.p('archives'),
            'APT::Architecture': self.arch, 'APT::Architectures::': self.arch,
            'Debug::NoLocking': '1', 'Acquire::Languages': 'none',
            'Acquire::IndexTargets::deb::Contents-deb::DefaultEnabled': 'false',
            'APT::Install-Recommends': 'false',
        }
        return [x for k, v in o.items() for x in ('-o', f'{k}={v}')]

    def apt(self, *args, quiet=False):
        env = dict(os.environ, APT_CONFIG='/dev/null', LC_ALL='C')
        cmd = ['apt-get', *self.opts(), *args]
        res = subprocess.run(cmd, env=env, text=True, capture_output=quiet)
        if res.returncode:
            if quiet:
                sys.stderr.write(res.stdout + res.stderr)
            raise SystemExit(f'[ERROR] apt-get {args[0]} failed for {self.suite}/{self.arch}')
        return res.stdout if quiet else ''

    def stanzas(self):
        out = []
        for name in sorted(os.listdir(self.p('lists'))):
            if name.endswith('_Packages'):
                with open(self.p('lists/' + name), encoding='utf-8', errors='replace') as fh:
                    out += parse_packages(fh.read())
        return out

    def known(self, stanzas, names):
        have = {f['Package'] for f in stanzas} | {p.split()[0] for f in stanzas for p in f.get('Provides', '').split(',') if p.strip()}
        return [n for n in names if n in have], [n for n in names if n not in have]


def build(arch, suite, components, out, mirror, keyring, cache):
    tag = f'{suite}-{arch}'
    log(f'\n=== {tag}: {", ".join(components)} ===')
    apt = AptTarget(os.path.join(cache, tag), suite, arch, mirror, keyring)
    log('[*] Fetching package index...')
    apt.apt('update', '-q', quiet=True)
    stanzas = apt.stanzas()
    with open(apt.p('dpkg/status'), 'w') as fh:
        fh.write(base_status(stanzas))
    pkgs = [p for c in components for p in COMPONENTS[c]]
    pkgs, missing = apt.known(stanzas, pkgs)
    for m in missing:
        log(f'[!] {m}: not available in {suite}/{arch}, skipped')
    for f in os.listdir(apt.p('archives')):
        if f.endswith('.deb'):
            os.remove(apt.p('archives/' + f))
    log(f'[*] Downloading {len(pkgs)} packages and their dependencies...')
    apt.apt('install', '-y', '-q', '--download-only', *pkgs, quiet=True)

    dest = os.path.join(out, tag)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.join(dest, 'debs'))
    debs = sorted(f for f in os.listdir(apt.p('archives')) if f.endswith('.deb'))
    names, index = local_index(stanzas, debs)
    for f in debs:
        shutil.move(apt.p('archives/' + f), os.path.join(dest, 'debs', names[f]))
    with open(os.path.join(dest, 'debs', 'Packages'), 'w') as fh:
        fh.write(index)

    py = python_version(stanzas)
    log(f'[*] Downloading Python wheels for Python {py}...')
    res = subprocess.run([sys.executable, '-m', 'pip', 'download', '-q', '--no-deps', '--only-binary=:all:',
                          '--platform', 'any', '--implementation', 'py', '--python-version', py,
                          '-d', os.path.join(dest, 'wheels'), *WHEELS])
    if res.returncode:
        raise SystemExit('[ERROR] pip download failed')

    manifest = {'suite': suite, 'arch': arch, 'python': py, 'components': components, 'packages': pkgs,
                'debs': len(debs), 'wheels': sorted(os.listdir(os.path.join(dest, 'wheels'))),
                'created': time.strftime('%Y-%m-%d %H:%M:%S')}
    with open(os.path.join(dest, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=2)
    tar = os.path.join(out, f'smms-offline-{tag}.tar')
    with tarfile.open(tar, 'w') as t:                 # .deb/.whl are already compressed
        t.add(dest, arcname=tag)
    size = os.path.getsize(tar) / 1e6
    log(f'[OK] {tag}: {len(debs)} debs, {len(manifest["wheels"])} wheels, Python {py} -> {tar} ({size:.1f} MB)')
    return tar


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--arch', default='armhf,arm64', help='comma-separated: armhf (H3), arm64 (H5) … [armhf,arm64]')
    ap.add_argument('--suite', default='bookworm', help='Debian release of the target (bookworm, trixie) [bookworm]')
    ap.add_argument('--components', default=','.join(DEFAULT_COMPONENTS),
                    help=f'comma-separated from {", ".join(COMPONENTS)} [{",".join(DEFAULT_COMPONENTS)}]')
    ap.add_argument('--out', default=os.path.join(ROOT, 'setup_data'))
    ap.add_argument('--mirror', default=MIRROR)
    ap.add_argument('--keyring', default=KEYRING)
    a = ap.parse_args(argv)

    arches = [x.strip() for x in a.arch.split(',') if x.strip()]
    comps = [x.strip() for x in a.components.split(',') if x.strip()]
    if 'core' not in comps:
        comps.insert(0, 'core')
    bad = [x for x in arches if x not in ARCHES] + [x for x in comps if x not in COMPONENTS]
    if bad:
        ap.error('unknown: ' + ', '.join(bad))
    if not re.fullmatch(r'[a-z]+', a.suite):
        ap.error('bad suite')
    if not shutil.which('apt-get'):
        raise SystemExit('[ERROR] apt-get not found — build the bundle on a Debian/Ubuntu machine')
    if not os.path.exists(a.keyring):
        raise SystemExit(f'[ERROR] {a.keyring} not found — install debian-archive-keyring or pass --keyring')
    if subprocess.run([sys.executable, '-m', 'pip', '--version'], capture_output=True).returncode:
        raise SystemExit('[ERROR] pip is needed to download wheels (apt install python3-pip)')
    os.makedirs(a.out, exist_ok=True)
    cache = os.path.join(a.out, '.cache')
    tars = [build(arch, a.suite, comps, a.out, a.mirror, a.keyring, cache) for arch in arches]
    log('\nCopy the project and ' + ', '.join(os.path.basename(t) for t in tars) +
        ' (into setup_data/) to the target, then run:  sudo ./install.sh --offline')


if __name__ == '__main__':
    main()
