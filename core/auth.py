"""Authentication helpers.

Access model:
  * anonymous  - may view services/status and run ``public_service_actions``;
  * logged in  - everything else.
When ``auth.enabled`` is false every visitor is treated as logged in.
"""
import hmac
from functools import wraps
from urllib.parse import urlparse

from flask import jsonify, redirect, request, session, url_for

from core import config


def auth_enabled():
    return bool(config.auth().get('enabled'))


def is_logged_in():
    return not auth_enabled() or bool(session.get('logged_in'))


def check_credentials(username, password):
    cfg = config.auth()
    return (hmac.compare_digest(str(username or ''), str(cfg.get('username', ''))) and
            hmac.compare_digest(str(password or ''), str(cfg.get('password', ''))))


def can_service_action(action):
    return is_logged_in() or action in config.public_service_actions()


def _wants_json():
    return request.path.startswith('/api/') or request.method != 'GET'


def unauthorized():
    """401 JSON for API/non-GET requests, redirect to the login page otherwise."""
    if _wants_json():
        return jsonify({'error': 'Unauthorized'}), 401
    return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))


def login_required(f):
    """Protect a page or API route. Use on every route that is not explicitly public."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            return unauthorized()
        return f(*args, **kwargs)
    return wrapper


def safe_next(url, default='/'):
    """Allow only same-site relative redirects after login."""
    if not url:
        return default
    parts = urlparse(url)
    if parts.scheme or parts.netloc or not url.startswith('/') or url.startswith('//'):
        return default
    return url
