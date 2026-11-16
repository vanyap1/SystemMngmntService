"""Main page (info panel). Public: the template hides blocks that require login.
With Settings → Access → home = test machine, anonymous visitors get the Tests page at ``/``; the info panel
stays at ``/main``."""
from flask import Blueprint, redirect, render_template, url_for

from core import auth, config
from core.shell import quote, run_command
from routes import services

bp = Blueprint('dashboard', __name__)


@bp.route('/')
def index():
    if not auth.is_logged_in() and config.public_access()['home'] == 'tests':
        return redirect(url_for('tests.tests'))
    return _render()


@bp.route('/main')
def main():
    return _render()


def _render():
    name = config.service_name()
    status = (run_command(f"sudo systemctl status {quote(name)}") if services._SERVICE_RE.match(name)
              else services.NO_TARGET)
    return render_template('index.html', status=status, backup_dir=config.backup_dir(),
                           show_archives=auth.can('backups'))
