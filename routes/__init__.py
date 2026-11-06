"""Flask blueprints. Register every new blueprint in BLUEPRINTS."""
from routes import (auth, backups, dashboard, devices, editor, git, help, i2c, logs, macros, net, pyrun, services,
                    settings, system, terminal, tests, udev, updates, video)

BLUEPRINTS = [
    auth.bp,
    dashboard.bp,
    services.bp,
    backups.bp,
    system.bp,
    devices.bp,
    i2c.bp,
    udev.bp,
    net.bp,
    editor.bp,
    pyrun.bp,
    terminal.bp,
    macros.bp,
    video.bp,
    tests.bp,
    logs.bp,
    help.bp,
    settings.bp,
    git.bp,
    updates.bp,
]
