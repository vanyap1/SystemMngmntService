# systemd services and logs

## User service (no root)

A service that runs as the user, e.g. a Python controller script.
File: `~/.config/systemd/user/opi-psu.service`

```ini
[Unit]
Description=OPi Power Supply Controller
After=default.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/vanya/opiPowerController.py
Restart=always
RestartSec=2
# Important: print() output reaches the journal immediately
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable opi-psu.service
systemctl --user start opi-psu.service
```

Start user services at boot, without an active login session:

```bash
loginctl enable-linger vanya
```

## System service

Same unit format, placed in `/etc/systemd/system/<name>.service` (add `User=` to drop root):

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now <name>.service
systemctl status <name>.service
```

## Journal

```bash
journalctl -u energyMonitor.service --since "2025-10-11 7:00"   # one unit since a time
journalctl -u <name> -f                                          # follow
journalctl -k -b -1                                              # kernel log of the previous boot
journalctl --list-boots                                          # boot history
```

## Kernel panic and watchdog

Reboot automatically instead of hanging. `/etc/sysctl.conf`:

```ini
kernel.panic = 10            # reboot 10 s after a panic
kernel.panic_on_oops = 1     # panic on driver errors (oops)
kernel.softlockup_panic = 1  # panic on a soft lockup
vm.panic_on_oom = 1          # panic when out of memory
```

Apply with `sudo sysctl -p`.

Test (⚠ the system really crashes / reboots):

```bash
echo c | sudo tee /proc/sysrq-trigger   # crash the kernel
echo b | sudo tee /proc/sysrq-trigger   # immediate reboot
echo f | sudo tee /proc/sysrq-trigger   # call the OOM killer
```

Hardware watchdog:

```bash
ls /dev/watchdog*          # /dev/watchdog  /dev/watchdog0
sudo apt install watchdog
sudo nano /etc/watchdog.conf
```

```ini
watchdog-device = /dev/watchdog
watchdog-timeout = 15
realtime = yes
priority = 1
```

```bash
sudo systemctl enable --now watchdog
```

> [!TIP]
> Run a command with redirection as root: `sudo sh -c 'echo 1 > /proc/sys/...'`.

## Free a port held by a process

```bash
sudo fuser -k 4200/tcp     # Linux
npx kill-port 4200         # Node.js tool, also works on Windows
```
