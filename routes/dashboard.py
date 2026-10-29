"""Main page. Public: the template hides blocks that require login."""
from flask import Blueprint, render_template

from core import config
from core.shell import quote, run_command

bp = Blueprint('dashboard', __name__)


@bp.route('/')
def index():
    status = run_command(f"sudo systemctl status {quote(config.service_name())}")
    return render_template('index.html', status=status, backup_dir=config.backup_dir())
