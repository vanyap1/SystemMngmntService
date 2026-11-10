"""Flask blueprints. Register every new blueprint in BLUEPRINTS."""
from routes import (auth, backups, dashboard, devices, editor, git, help, i2c, logs, macros, modbus, net, pyrun, services,
                    settings, sysclone, system, terminal, tests, ttyterm, udev, updates, video)

BLUEPRINTS = [
    auth.bp,
    dashboard.bp,
    services.bp,
    backups.bp,
    system.bp,
    devices.bp,
    i2c.bp,
    modbus.bp,
    ttyterm.bp,
    udev.bp,
    net.bp,
    sysclone.bp,
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
