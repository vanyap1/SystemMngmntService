"""SystemMngmntService entry point. Routes live in routes/, shared code in core/."""
from flask import Flask

from core import config, web
from routes import BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.secret_key = config.secret_key()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
    web.init_app(app)
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == '__main__':
    app.run(host=config.get('host', '0.0.0.0'), port=config.get('port', 80), threaded=True)
