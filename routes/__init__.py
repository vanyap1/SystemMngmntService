"""Flask blueprints. Register every new blueprint in BLUEPRINTS."""
from routes import auth, backups, dashboard, devices, editor, macros, net, services, settings, system, tests, udev, video

BLUEPRINTS = [
    auth.bp,
    dashboard.bp,
    services.bp,
    backups.bp,
    system.bp,
    devices.bp,
    udev.bp,
    net.bp,
    editor.bp,
    macros.bp,
    video.bp,
    tests.bp,
    settings.bp,
]
