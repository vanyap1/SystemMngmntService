# Python

## Kivy

```bash
sudo apt update
sudo apt install python3-pip libgl1-mesa-dri libgles2-mesa libegl1-mesa libsdl2-2.0-0
pip3 install --user --upgrade pip
pip3 install --user "kivy[base]" kivy_examples
pip install kivy_garden.graph --break-system-packages
```

> [!NOTE]
> On Debian 12+ pip refuses to install into the system Python (PEP 668). Prefer `apt install python3-<pkg>`
> or a venv (`python3 -m venv ~/venv`); `--break-system-packages` is the last resort.

## Run a script as a service

See [systemd services](systemd-and-logs.md#user-service-no-root). Set `Environment=PYTHONUNBUFFERED=1` so
`print()` output appears in `journalctl` immediately.

## Move packages between machines

See [Storage → Installing the panel offline](storage-backup.md#installing-the-panel-offline).
