"""Template context shared by every page (see templates/base.html)."""
import os

from flask import request, send_from_directory, url_for

from core import auth, config, nav


def asset(filename):
    """URL of a static file with an mtime cache-buster."""
    try:
        version = int(os.path.getmtime(os.path.join(config.BASE_DIR, 'static', filename)))
    except OSError:
        version = 0
    return url_for('static', filename=filename, v=version)


def _context():
    logged_in = auth.is_logged_in()
    app_title = config.get('app_title', 'SystemMngmntService')
    return {
        'app_title':    app_title,
        'page_title':   config.get('page_title', app_title),
        'device_name':  config.get('device_name', ''),
        'service_name': config.service_name(),
        'logged_in':    logged_in,
        'auth_enabled': auth.auth_enabled(),
        'nav_items':    nav.visible_items(logged_in, request.endpoint),
        'can_service':  auth.can_service_action,
        'asset':        asset,
        # Exposed to JS as window.APP_CONFIG (see static/js/core.js).
        'app_js': {
            'serviceName':          config.service_name(),
            'loggedIn':             logged_in,
            'publicServiceActions': config.public_service_actions(),
            'loginUrl':             url_for('auth.login'),
        },
    }


def init_app(app):
    app.context_processor(_context)

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.static_folder, 'img'), 'favicon.png',
                                   mimetype='image/png')
