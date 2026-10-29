"""Device browser: grouped device list, /dev tree, buses (USB/PCI/I2C), GPIO overview and control."""
import glob
import grp
import os
import pwd
import re
import stat

from flask import Blueprint, jsonify, request

from core import udev
from core.auth import login_required
from core.gpio_ctl import GpioError, gpio_ctl
from core.shell import quote, resolve_inside, sh
from core.test_runner import runner

bp = Blueprint('devices', __name__)

DEV_ROOT = '/dev'
MAX_DEPTH = 6
MAX_ENTRIES = 5000


def _user(uid, cache={}):
    if uid not in cache:
        try:
            cache[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            cache[uid] = str(uid)
    return cache[uid]


def _group(gid, cache={}):
    if gid not in cache:
        try:
            cache[gid] = grp.getgrgid(gid).gr_name
        except KeyError:
            cache[gid] = str(gid)
    return cache[gid]


def _entry_type(mode):
    if stat.S_ISDIR(mode):
        return 'dir'
    if stat.S_ISCHR(mode):
        return 'char'
    if stat.S_ISBLK(mode):
        return 'block'
    if stat.S_ISLNK(mode):
        return 'link'
    if stat.S_ISSOCK(mode):
        return 'socket'
    if stat.S_ISFIFO(mode):
        return 'fifo'
    return 'file'


def _scan_dev(path, depth, counter):
    """Return the entries of ``path`` as nested dicts; symlinks are never followed."""
    try:
        entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
    except OSError:
        return []
    nodes = []
    for e in entries:
        if counter[0] >= MAX_ENTRIES:
            break
        counter[0] += 1
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        kind = _entry_type(st.st_mode)
        node = {
            'name':  e.name,
            'path':  e.path,
            'type':  kind,
            'mode':  stat.filemode(st.st_mode),
            'owner': _user(st.st_uid),
            'group': _group(st.st_gid),
        }
        if kind in ('char', 'block'):
            node['dev'] = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
        elif kind == 'link':
            try:
                node['target'] = os.readlink(e.path)
            except OSError:
                node['target'] = '?'
            node['broken'] = not os.path.exists(e.path)
        elif kind == 'dir':
            node['children'] = _scan_dev(e.path, depth + 1, counter) if depth < MAX_DEPTH else []
        nodes.append(node)
    return nodes


@bp.route('/api/devices/dev')
@login_required
def api_dev_tree():
    counter = [0]
    tree = _scan_dev(DEV_ROOT, 1, counter)
    return jsonify({'root': DEV_ROOT, 'tree': tree, 'count': counter[0],
                    'truncated': counter[0] >= MAX_ENTRIES})


@bp.route('/api/devices/dev/info')
@login_required
def api_dev_info():
    """udev properties of a device node (``path`` in /dev) or of a sysfs device (``devpath``)."""
    path = request.args.get('path', '')
    devpath = request.args.get('devpath', '')
    if devpath:
        real = resolve_inside('/sys' + devpath, '/sys/devices')
        if not real:
            return jsonify({'error': 'devpath must be inside /sys/devices'}), 400
        out = sh(f"udevadm info --query=all --path={quote(real)}")
    else:
        real = resolve_inside(path, DEV_ROOT)
        if not real:
            return jsonify({'error': 'Path must be inside /dev'}), 400
        out = sh(f"udevadm info --query=all --name={quote(real)}")
    info = {'path': path, 'real': real, 'devpath': '', 'symlinks': [], 'props': {}}
    for line in out.split('\n'):
        key, _, value = line.partition(': ')
        if key == 'P':
            info['devpath'] = value
        elif key == 'S':
            info['symlinks'].append('/dev/' + value)
        elif key == 'E':
            name, _, val = value.partition('=')
            info['props'][name] = val
    if not out:
        info['error'] = 'No udev information for this node'
    return jsonify(info)


@bp.route('/api/devices/list')
@login_required
def api_device_list():
    """Device nodes from the udev database, grouped by kind."""
    return jsonify(udev.device_list())


@bp.route('/api/devices/buses')
@login_required
def api_buses():
    """USB topology (like lsusb -t), PCI devices (lspci -k) and I2C adapters with clients."""
    return jsonify({'usb': udev.usb_devices(), 'pci': udev.pci_devices(), 'i2c': udev.i2c_buses()})


@bp.route('/api/devices/usb/verbose')
@login_required
def api_usb_verbose():
    """Descriptors of one USB device (lsusb -v -s bus:dev); without arguments lsusb + lsusb -t."""
    if not request.args.get('bus'):
        return jsonify({'text': sh('lsusb 2>&1; echo; lsusb -t 2>&1', timeout=10) or 'lsusb is not available'})
    try:
        bus, dev = int(request.args.get('bus', '')), int(request.args.get('dev', ''))
    except ValueError:
        return jsonify({'error': 'bus and dev must be numbers'}), 400
    out = sh(f"lsusb -v -s {bus:03d}:{dev:03d} 2>&1", timeout=10)
    return jsonify({'text': out or 'lsusb returned nothing (is usbutils installed?)'})


# ── GPIO ─────────────────────────────────────────────────────────────────

def _sysfs_bases():
    """Map chip label -> legacy sysfs base number (global GPIO numbering)."""
    bases = {}
    for chip_dir in glob.glob('/sys/class/gpio/gpiochip*'):
        try:
            with open(os.path.join(chip_dir, 'label')) as f:
                label = f.read().strip()
            with open(os.path.join(chip_dir, 'base')) as f:
                bases[label] = int(f.read().strip())
        except (OSError, ValueError):
            pass
    return bases


def _chip_paths():
    paths = glob.glob('/dev/gpiochip*')
    return sorted(paths, key=lambda p: int(re.sub(r'\D', '', p) or 0))


def _enum_name(value):
    """'Direction.INPUT' / Bias.PULL_UP -> 'input' / 'pull-up' (libgpiod v2 enums)."""
    return getattr(value, 'name', str(value)).lower().replace('_', '-')


def _chip_v2(gpiod, path):
    with gpiod.Chip(path) as chip:
        info = chip.get_info()
        lines = []
        for offset in range(info.num_lines):
            li = chip.get_line_info(offset)
            lines.append({
                'offset':    offset,
                'name':      li.name or '',
                'consumer':  li.consumer or '',
                'direction': _enum_name(li.direction),
                'active':    'low' if li.active_low else 'high',
                'used':      bool(li.used),
                'bias':      _enum_name(li.bias),
                'drive':     _enum_name(li.drive),
            })
        return {'name': info.name, 'label': info.label, 'lines': lines}


def _chip_v1(gpiod, path):
    bias_names = {gpiod.Line.BIAS_AS_IS: 'as-is', gpiod.Line.BIAS_DISABLE: 'disabled',
                  gpiod.Line.BIAS_PULL_UP: 'pull-up', gpiod.Line.BIAS_PULL_DOWN: 'pull-down'}
    chip = gpiod.Chip(path)
    try:
        lines = []
        for offset in range(chip.num_lines()):
            line = chip.get_line(offset)
            drive = ('open-drain' if line.is_open_drain() else
                     'open-source' if line.is_open_source() else 'push-pull')
            lines.append({
                'offset':    offset,
                'name':      line.name() or '',
                'consumer':  line.consumer() or '',
                'direction': 'output' if line.direction() == gpiod.Line.DIRECTION_OUTPUT else 'input',
                'active':    'low' if line.active_state() == gpiod.Line.ACTIVE_LOW else 'high',
                'used':      bool(line.is_used()),
                'bias':      bias_names.get(line.bias(), 'unknown'),
                'drive':     drive,
            })
        return {'name': chip.name(), 'label': chip.label(), 'lines': lines}
    finally:
        chip.close()


@bp.route('/api/devices/gpio')
@login_required
def api_gpio():
    """All GPIO chips and their lines. Read-only: no line is requested or changed."""
    try:
        import gpiod
    except ImportError:
        raw = sh('gpioinfo 2>&1')
        return jsonify({'chips': [], 'raw': raw,
                        'error': 'Python module gpiod is not installed — showing gpioinfo output'})

    read_chip = _chip_v2 if hasattr(gpiod, 'request_lines') else _chip_v1
    bases = _sysfs_bases()
    chips = []
    for path in _chip_paths():
        try:
            chip = read_chip(gpiod, path)
        except Exception as e:  # permission denied, busy driver, API mismatch...
            chips.append({'path': path, 'name': os.path.basename(path), 'label': '',
                          'lines': [], 'error': str(e)})
            continue
        chip['path'] = path
        chip['base'] = bases.get(chip['label'])
        chips.append(chip)
    return jsonify({'chips': chips})


# ── GPIO control (lines are held only while the GPIO tab is open) ────────

gpio_ctl.blocked = lambda: 'A test script is running — GPIO control is locked' if runner.is_running() else None


@bp.route('/api/devices/gpio/ctl')
@login_required
def api_gpio_ctl_state():
    """Lines held by this client with their current values; also keeps the lease alive."""
    try:
        return jsonify(gpio_ctl.snapshot(request.args.get('client')))
    except GpioError as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/devices/gpio/ctl', methods=['POST'])
@login_required
def api_gpio_ctl():
    """{client, action: claim|input|output|set|release|release_all, chip, offset, value}"""
    data = request.get_json(silent=True) or {}
    client, action = data.get('client'), data.get('action')
    chip, offset, value = data.get('chip'), data.get('offset'), data.get('value')
    try:
        if action == 'claim':
            state = gpio_ctl.claim(client, chip, offset)
        elif action in ('input', 'output'):
            state = gpio_ctl.configure(client, chip, offset, action, value)
        elif action == 'set':
            state = gpio_ctl.set_value(client, chip, offset, value)
        elif action == 'release':
            state = gpio_ctl.release(client, chip, offset)
        elif action == 'release_all':
            state = gpio_ctl.release_client(client)
        else:
            return jsonify({'error': 'Unknown action'}), 400
    except GpioError as e:
        return jsonify({'error': str(e)}), 409
    return jsonify(state)
