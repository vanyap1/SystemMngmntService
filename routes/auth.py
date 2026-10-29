"""Login / logout."""
from flask import Blueprint, redirect, render_template, request, session, url_for

from core import auth

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    next_url = auth.safe_next(request.args.get('next'))
    if not auth.auth_enabled():
        return redirect(next_url)
    error = None
    if request.method == 'POST':
        if auth.check_credentials(request.form.get('login'), request.form.get('password')):
            session.clear()
            session['logged_in'] = True
            return redirect(next_url)
        error = 'Invalid username or password'
    return render_template('login.html', error=error)


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('dashboard.index'))
