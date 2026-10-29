"""Shared test setup: the Flask app with an in-memory config that never touches live files.

Import this module before anything from the project. It loads config.json read-only, then points
CONFIG_PATH and test_logs_dir to a temporary directory so a test can never overwrite live settings
or add run logs, and forces known credentials (auth enabled, user/password ``test``).
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app          # noqa: E402  (loads config.json)
from core import config      # noqa: E402

TMP = tempfile.mkdtemp(prefix='smms-tests-')
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

config.CONFIG_PATH = os.path.join(TMP, 'config.json')
config.CFG['auth'] = {'enabled': True, 'username': 'test', 'password': 'test'}
config.CFG['public_service_actions'] = ['restart']
config.CFG['test_logs_dir'] = os.path.join(TMP, 'testLogs')
app.config['TESTING'] = True

USER, PASSWORD = 'test', 'test'


def client(logged_in=False):
    c = app.test_client()
    if logged_in:
        r = c.post('/login', data={'login': USER, 'password': PASSWORD})
        assert r.status_code == 302, r.status_code
    return c
