"""Second panel instance for manual/visual checks; never touches the live service.

    python3 tests/devserver.py [--port 5099] [--auth] [--target DIR] [--help-dir DIR]

Auth is disabled in memory unless --auth is given. Saved settings and test-run logs go to a temp dir. Any HTML page accepts
``?js=<code>``: the code runs after the page loads — handy for headless screenshots of popups,
e.g. ``/settings?js=MonitorFloat.open()``. URL-encode "+" as %2B.
"""
import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import request  # noqa: E402

from app import app  # noqa: E402
from core import config  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5099)
parser.add_argument('--auth', action='store_true', help='keep login enabled (anonymous view)')
parser.add_argument('--logs', help='test logs directory to show (default: an empty temp dir)')
parser.add_argument('--target', help='target_dir to use instead of the configured one (code editor, Git)')
parser.add_argument('--help-dir', help='documentation folder to use instead of the configured one (Docs, diagrams)')
parser.add_argument('--fake-update', action='store_true',
                    help='pretend the panel upstream has new commits (shows the update button; nothing is fetched)')
parser.add_argument('--fake-i2c', action='store_true', help='simulated I²C bus (tests/fake_i2c.py) instead of the real ones')
args = parser.parse_args()

tmp = tempfile.mkdtemp(prefix='smms-devserver-')
config.CONFIG_PATH = os.path.join(tmp, 'config.json')   # settings saves never reach the live config.json
config.CFG['test_logs_dir'] = os.path.abspath(args.logs) if args.logs else os.path.join(tmp, 'testLogs')
config.CFG['modbus_sessions_dir'] = os.path.join(tmp, 'modbusSessions')
config.CFG['tty_sessions_dir'] = os.path.join(tmp, 'ttySessions')
if args.target:
    config.CFG['target_dir'] = os.path.abspath(args.target)
if args.help_dir:
    config.CFG['help_dir'] = os.path.abspath(args.help_dir)
if not args.auth:
    config.CFG['auth']['enabled'] = False
if args.fake_i2c:
    from tests import fake_i2c
    fake_i2c.install()
    config.CFG['i2c_labels'] = {str(fake_i2c.BUS): {'0x41': 'INA228 power monitor (EXT1)'}}
config.CFG['update_check_minutes'] = 0                  # never fetch the real upstream from a dev server
if args.fake_update:
    from core import updates
    updates._state.update(checked=time.time(), online=True, branch='main', upstream='origin/main', behind=3, dirty=1,
                          commits=[{'hash': 'f' * 40, 'short': 'f00ba12', 'author': 'dev', 'when': '2 hours ago',
                                    'subject': 'Navigation: sections with sub-pages'},
                                   {'hash': 'e' * 40, 'short': 'e1d2c3b', 'author': 'dev', 'when': '1 day ago',
                                    'subject': 'Editor: lazy file tree'},
                                   {'hash': 'd' * 40, 'short': 'd4e5f6a', 'author': 'dev', 'when': '3 days ago',
                                    'subject': 'Installer with offline bundles'}])


@app.after_request
def inject_js(response):
    js = request.args.get('js')
    if js and response.mimetype == 'text/html':
        hook = f'<script>addEventListener("load", () => {{ {js} }})</script></body>'
        response.set_data(response.get_data(as_text=True).replace('</body>', hook))
    return response


app.run(host='127.0.0.1', port=args.port)
