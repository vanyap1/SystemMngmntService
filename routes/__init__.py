"""Flask blueprints. Register every new blueprint in BLUEPRINTS."""
from routes import auth, backups, dashboard, editor, macros, services, settings, system, tests, video

BLUEPRINTS = [
    auth.bp,
    dashboard.bp,
    services.bp,
    backups.bp,
    system.bp,
    editor.bp,
    macros.bp,
    video.bp,
    tests.bp,
    settings.bp,
]
