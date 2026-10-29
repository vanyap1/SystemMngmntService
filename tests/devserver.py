"""Second panel instance for manual/visual checks; never touches the live service.

    python3 tests/devserver.py [--port 5099] [--auth]

Auth is disabled in memory unless --auth is given. Saved settings and test-run logs go to a temp dir. Any HTML page accepts
``?js=<code>``: the code runs after the page loads — handy for headless screenshots of popups,
e.g. ``/settings?js=MonitorFloat.open()``. URL-encode "+" as %2B.
"""
import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import request  # noqa: E402

from app import app  # noqa: E402
from core import config  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, default=5099)
parser.add_argument('--auth', action='store_true', help='keep login enabled (anonymous view)')
parser.add_argument('--logs', help='test logs directory to show (default: an empty temp dir)')
args = parser.parse_args()

tmp = tempfile.mkdtemp(prefix='smms-devserver-')
config.CONFIG_PATH = os.path.join(tmp, 'config.json')   # settings saves never reach the live config.json
config.CFG['test_logs_dir'] = os.path.abspath(args.logs) if args.logs else os.path.join(tmp, 'testLogs')
if not args.auth:
    config.CFG['auth']['enabled'] = False


@app.after_request
def inject_js(response):
    js = request.args.get('js')
    if js and response.mimetype == 'text/html':
        hook = f'<script>addEventListener("load", () => {{ {js} }})</script></body>'
        response.set_data(response.get_data(as_text=True).replace('</body>', hook))
    return response


app.run(host='127.0.0.1', port=args.port)
