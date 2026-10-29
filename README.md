# SystemMngmntService

A self-contained web panel for single-board Linux machines (OrangePi, NanoPi, Raspberry Pi …) that run one
main application as a systemd service — and, optionally, a hardware test fixture.
It runs as its own systemd unit, so it stays reachable when the application crashes or is being redeployed.

Flask 3 + plain JavaScript, no build step; the only server dependency is `python3-flask` from apt.
**Works fully offline** (closed networks): Font Awesome, the Monaco editor and xterm.js are vendored in
`static/vendor`, the monitor charts are drawn on canvas — the browser never contacts the internet.

![Dashboard](docs/img/dashboard.png)

## Features

| | |
|---|---|
| **Service control** | status / start / stop / restart of the target service and any other systemd unit |
| **System monitor** | CPU, RAM, temperature, active network interface and block devices with live charts; on the main page and as a floating, resizable, semi-transparent window on every other page |
| **Backups & deploy** | archive the project, upload a `.tar.gz`, deploy it with an automatic backup |
| **Code editor** | file tree, Monaco editor with outline, service log, web terminal, command macros |
| **Test platform** | run `*_test.py` fixture sequences, live PASS/FAIL table, operator prompts, stop-on-fail, a log per run, yield statistics |
| **Log viewer** | filter runs by script / verdict / serial / date, yield and first-pass yield, top failing steps, parsed log view, per-step value analysis (Cpk), CSV export |
| **Devices** | logical device list, `/dev` tree, USB/PCI/I²C buses (`lsusb` / `lspci`), network interfaces and **CAN bus** (bitrate, RX trace, TX with repeat timer), **GPIO** viewer and manual control, **udev** events / rules editor / tools |
| **Video** | preview of V4L2 cameras |
| **Per-host config** | one repository deployed to several machines, each with its own section in `config.json` |
| **Simple access model** | anonymous operators see only the target service (restart) and the read-only monitor; everything else needs a login |

## Screenshots

| Anonymous operator view | Floating monitor on another page |
|---|---|
| ![Anonymous view](docs/img/dashboard-anonymous.png) | ![Monitor window](docs/img/monitor-window.png) |

| Test platform | Code editor |
|---|---|
| ![Tests](docs/img/tests.png) | ![Editor](docs/img/editor.png) |

| Devices — buses | Devices — network |
|---|---|
| ![Buses](docs/img/devices-buses.png) | ![Network](docs/img/devices-network.png) |

| Test log viewer | Step analysis |
|---|---|
| ![Logs](docs/img/logs.png) | ![Step analysis](docs/img/logs-step.png) |

| Devices — GPIO | Devices — udev rules |
|---|---|
| ![GPIO](docs/img/devices-gpio.png) | ![udev](docs/img/devices-udev.png) |

## Quick start

```bash
git clone <this repo> && cd SystemMngmntService
sudo bash setup.sh          # installs python3-flask, registers and starts systemmngmntservice.service
```

Open `http://<device>/`, log in (default `admin` / `admin` — change it in **Settings**) and set the target
service, project and backup directories. See [Installation](#installation) and [Configuration](#configuration-configjson).

---

## Project Structure

```
SystemMngmntService/
├── app.py            # Entry point: creates the Flask app and registers blueprints
├── config.json       # Configuration (paths, port, service, authentication)
├── macros.json       # Code editor command macros
├── core/             # Shared backend: config, auth, shell helpers, navigation, template context
├── routes/           # One Flask blueprint per feature (dashboard, services, backups, editor, ...)
├── templates/
│   ├── base.html     # Common layout: top bar, shared modals and scripts
│   ├── partials/     # Reusable fragments (services modal, video, power menu, flash)
│   ├── index.html    # Main dashboard
│   ├── editor.html   # Code editor
│   ├── settings.html # Settings page
│   └── login.html    # Login page
├── static/
│   ├── css/          # base.css + components.css (shared), <page>.css
│   ├── vendor/       # Font Awesome, Monaco, xterm.js served locally (offline), see vendor/README.md
│   ├── js/           # core.js, services.js, sysinfo.js, monitor.js, video.js, power.js, devices*.js (shared), <page>.js
│   └── img/
├── testPlatform/     # Test platform: *_test.py sequences + hardware drivers (run from the Tests page)
├── testLogs/         # One log file per test run (git-ignored)
├── tests/            # Unit/integration tests (unittest) + dev server and screenshot helpers
├── docs/img/         # README screenshots (regenerate with tests/docs_screenshots.sh)
├── CLAUDE.md         # Development rules (for humans and AI assistants)
└── setup.sh          # Installation and systemd registration script
```

See `CLAUDE.md` for how to add pages and API endpoints.

---

## Configuration (`config.json`)

One config file serves every machine the project is deployed to:

```json
{
    "default": { "target_dir": "...", "service_name": "...", "auth": { ... } },
    "hosts": {
        "orangepi3b": { "device_name": "NAS", "target_dir": "...", ... }
    }
}
```

- The machine is identified by its hostname.
- A host without its own section uses `default` (missing keys fall back to built-in defaults).
- Saving on the Settings page stores the settings in the section of the current host; from then on that host
  uses its own values. "Reset to defaults" on the Settings page removes the section.
- An old flat `config.json` is converted automatically on first start.

Fields (same in `default` and in a host section):

| Field | Description |
|---|---|
| `target_dir` | Target application directory |
| `backup_dir` | Directory for archive storage |
| `archive_name` | Default archive filename |
| `service_name` | Name of the systemd service to monitor |
| `host` / `port` | Panel listen address |
| `auth.enabled` | Enable / disable login |
| `auth.username` / `auth.password` | Credentials |
| `public_service_actions` | Service actions allowed without login (default `["restart"]`) |

---

## Main Flow

```mermaid
flowchart TD
    Browser -->|HTTP| Panel[SystemMngmntService :81]
    Panel -->|systemctl| Target[Target service]
    Panel -->|tar / extract| Files[Application directory]
    Panel -->|read / write| Files
```

---

## Routes

### Dashboard (`/`)

```mermaid
flowchart LR
    Dashboard --> ServiceControl[Service status\nstart / stop / restart]
    Dashboard --> Monitor[System monitor\nCPU / RAM / network charts\ntemperature, block devices]
    Dashboard --> Archives[Archive list]
    Archives --> Deploy[Deploy]
    Archives --> Download[Download]
    Archives --> Delete[Delete]
```

### Backup and Deploy

```mermaid
sequenceDiagram
    participant User
    participant Panel
    participant Service as Target service
    participant FS as File system

    User->>Panel: POST /deploy {filename}
    Panel->>Service: systemctl stop
    Panel->>FS: tar -czf pre_deploy_*.tar.gz (auto-backup)
    Panel->>FS: tar -xzf <filename>
    Panel->>Service: systemctl start
    Panel-->>User: {success, auto_backup}

    User->>Panel: POST /backups/create
    Panel->>Service: systemctl stop
    Panel->>FS: tar -czf <archive>
    Panel->>Service: systemctl start
    Panel-->>User: redirect /
```

### Code Editor (`/editor`)

```mermaid
flowchart LR
    Editor -->|GET /api/tree| FileTree[File tree]
    Editor -->|GET /api/file?path=...| ReadFile[File contents]
    Editor -->|POST /api/file| SaveFile[Save file]
    Editor -->|POST /api/exec| Shell[Execute command]
```

---

## API

| Method | Route | Access | Description |
|---|---|---|---|
| GET | `/api/services` | public | systemd services (JSON); anonymous: only the target service |
| GET | `/api/status?name=` | public | `systemctl status` output; anonymous: target service only |
| POST | `/api/service/<start\|stop\|restart>?name=` | public for `public_service_actions`, else login | Service action |
| GET | `/api/sysinfo` | login | CPU, RAM, network, disks (JSON; editor side panel) |
| GET | `/api/monitor?since=` | public | System monitor: current CPU/RAM/temperature/active interface/disk I/O, block devices, chart history newer than `since` |
| POST | `/api/power/<reboot\|poweroff>` | login | Reboot / shut down |
| GET | `/api/backups` | login | Archive list (JSON) |
| POST | `/backups/create` | login | Create archive (form) |
| POST | `/backups/upload` | login | Upload archive (multipart form) |
| GET | `/backups/download/<name>` | login | Download archive |
| POST | `/api/backups/deploy` | login | Deploy archive (with auto-backup) |
| POST | `/api/backups/delete` | login | Delete archive |
| GET | `/api/tree` | login | File tree of the target directory |
| GET/POST | `/api/file` | login | Read / write file |
| POST | `/api/file_create`, `/api/file_rename`, `/api/file_delete` | login | File operations |
| GET | `/api/file_raw` | login | Raw file (image preview) |
| POST | `/api/exec` | login | Execute shell command |
| GET/POST | `/api/macros` | login | Editor command macros |
| GET | `/api/video_devices`, `/api/video_resolutions`, `/api/video_feed` | login | Video streaming |
| POST | `/api/video_stop` | login | Stop video stream |
| GET | `/api/browse` | login | Browse directories (settings path picker) |
| GET | `/api/devices/dev` | login | `/dev` tree (type, maj:min, mode, owner, symlink target) |
| GET | `/api/devices/dev/info?path=\|devpath=` | login | `udevadm info` properties of a node in `/dev` or a `/devices/...` path |
| GET | `/api/devices/list` | login | Device nodes from the udev database, grouped by kind |
| GET | `/api/devices/buses` | login | USB topology, PCI devices, I²C adapters and clients |
| GET | `/api/devices/usb/verbose[?bus=&dev=]` | login | `lsusb -v -s bus:dev`, or `lsusb` + `lsusb -t` |
| GET | `/api/devices/gpio` | login | GPIO chips and lines like `gpioinfo` (read-only, libgpiod v1/v2) |
| GET | `/api/devices/gpio/ctl?client=` | login | Lines held by a popup client with live values (also renews its lease) |
| POST | `/api/devices/gpio/ctl` | login | `{client, action: claim\|input\|output\|set\|release\|release_all, chip, offset, value}` |
| GET | `/api/net/interfaces` | login | Interfaces (state, addresses, counters, CAN bit timing), routes, DNS |
| POST | `/api/net/can/link` | login | `{iface, action: open\|close, bitrate, sample_point, restart_ms, listen_only}` |
| GET | `/api/net/can/frames?iface=&since=` | login | New CAN frames + cyclic jobs; polling keeps the socket open |
| POST | `/api/net/can/send` | login | `{iface, action: send\|cyclic\|stop\|stop_all\|clear, id, ext, rtr, data, period_ms, job}` |
| GET | `/api/udev/status` | login | systemd-udevd state, udev version, rules counts, subsystems |
| POST | `/api/udev/action` | login | `{action: reload\|restart\|trigger\|test\|attrs, kind, subsystem, device, devpath, all}` |
| GET | `/api/udev/events?since=` | login | New monitor events; polling keeps `udevadm monitor` running |
| POST | `/api/udev/events/clear` | login | Clear the event buffer |
| GET | `/api/udev/rules` | login | Rules files of `/etc`, `/run`, `/lib` with override info |
| GET | `/api/udev/rule?dir=&name=` | login | Read one rules file |
| POST | `/api/udev/rule` | login | Save `{name, text, force}` to `/etc/udev/rules.d` (422 on syntax problems unless `force`) |
| POST | `/api/udev/rule/check` | login | Syntax check `{text}` → `{problems: [{line, message}]}` |
| POST | `/api/udev/rule/delete` | login | Delete `{name}` from `/etc/udev/rules.d` |
| POST | `/api/settings` | login | Save settings |
| GET | `/api/tests/scripts` | login | Test scripts (`*_test.py` in `tests_dir`) |
| POST | `/api/tests/start` / `/api/tests/stop` | login | Start `{script, serial, stop_on_fail}` / stop the running one |
| GET | `/api/tests/status?run_id=&results_from=&output_from=` | login | Current run, incremental results, output and pending operator prompt |
| POST | `/api/tests/answer` | login | Answer the pending operator prompt `{run_id, prompt_id, value}` |
| GET | `/api/tests/logs`, `/api/tests/logs/<name>[?download=1]` | login | Run history / log file |
| POST | `/api/tests/logs/delete` | login | Delete `{name}` or `{all: true}` |
| GET | `/logs` | login | Test log viewer page |
| GET | `/api/logs?script&verdict&q&from&to&step&offset&limit` | login | Filtered runs (newest first) + statistics (yield, first-pass yield, top failing steps) |
| GET | `/api/logs/view/<name>` | login | One log parsed into header, steps, sections, output, operator Q/A, footer |
| GET | `/api/logs/step?name=&…filters` | login | One step across the filtered runs: values, min/mean/max/σ, Cpk |
| GET | `/api/logs/export.csv?…filters` | login | Filtered runs as CSV (one row per run) |
| GET | `/api/tests/stats?script=` | login | Board counts per verdict for a script |

---

## System monitor

The **System Monitor** card on the main page is public (read-only, also for anonymous visitors); for
logged-in users the **Monitor** button in the top bar of every other page opens the same view in a floating window (drag by the title bar, resize from the
bottom-right corner, opacity slider, ×). Position, size, opacity and the open state are remembered in the
browser, so the window stays open while moving between pages.

- Tiles: CPU % (per-core bars, frequency, load average), RAM, swap, temperature (all thermal zones, CPU first),
  active network interface rates, uptime / processes.
- Charts (1 / 5 / 15 min window, hover for values): CPU %, RAM %, network RX/TX of the active interface.
- Block devices (`lsblk`, loop/ram skipped): size, model/transport, NVMe temperature, filesystem/swap usage,
  mount points, read/write rate and busy %.
- Active interface = the default route with the lowest metric (otherwise the first link that is up):
  state, carrier, speed, addresses, gateway, MAC/MTU, totals, errors/drops.

`core/monitor.py` samples `/proc` and `/sys` once per second and keeps 15 minutes of history. The sampler
runs only while the page polls `/api/monitor` (30 s lease); the browser polls every 2 s and pauses in a hidden tab.

---

## Devices popup

The **Devices** button in the top bar (logged in) opens a popup with six tabs. With *Auto* on, the
current view refreshes every 2–3 s; new devices are highlighted, added/removed ones are listed in the
footer (plus a toast, except `/dev/pts`, `/dev/shm`). All groups, trees, chips, bus sections and rules
directories start collapsed (a filter expands what matches; *Expand* / *Collapse* buttons). Clicking a device opens a side panel with its udev
properties and actions: *Attributes* (`udevadm info -a`), *Test rules* (`udevadm test`, dry run),
*Trigger change*, *New rule…* (drafts a rule matching the device and opens it in the rules editor).

- **Devices** — the udev database grouped by kind: serial ports, USB, video, I²C, SPI, GPIO, storage,
  input, sound, network, display, other, virtual (hidden by default). Human names (hwdb vendor/model,
  V4L product, disk model/size/filesystem), driver, VID:PID, symlinks.
- **/dev** — the device node tree (symlinks are not followed) with a group and a text filter.
- **Buses** — USB topology like `lsusb -t` (VID:PID, hwdb names, serial, speed, interface class → driver,
  device nodes of each device; 🔍 = `lsusb -v`), PCI (`lspci -k`), I²C adapters with the clients the kernel
  knows about (the bus is never scanned).
- **Network**
  - *Interfaces* — every interface with type, state, IPv4/IPv6, MAC, RX/TX rate and errors; a row expands to
    MTU, driver, link speed, packet counters (and bit timing / bus state / error counters for CAN).
    *Routes & DNS* below. Read-only: interfaces other than CAN are never reconfigured.
  - *CAN bus* — SocketCAN tool for `can*` / `vcan*`: *Open* applies bitrate, sample point, restart-ms,
    listen-only (`ip link set … type can …`, root) and brings the link up, *Close* brings it down (vcan: up/down
    only). Frames (RX, own TX, error frames with decoded class) in *Trace* or *By ID* (count, period, changed
    bytes highlighted). Send a frame (hex ID, Ext, RTR, hex data) or *Start repeat* every N ms; running
    repeats are listed with counters and a Stop button. The socket and all repeats exist only while the
    CAN view is open (leaving it stops the repeats, an idle client loses them after 10 s). Configuration is
    locked while a test script runs; starting a test stops all repeats.
- **GPIO** — every `/dev/gpiochip*` with its lines: offset, global sysfs number (`base + offset`), name,
  consumer, direction, active level, bias/drive flags. Without the Python `gpiod` module the raw
  `gpioinfo` output is shown.
  *Claim* requests a free line "as is" (its state is not changed), then it can be switched IN/OUT, an output
  toggled 0/1, an input level is read every second. Lines are held only while the GPIO tab is open:
  switching the tab, closing the popup or the page releases them, and a client that stops polling loses
  them after 6 s (`core/gpio_ctl.py`, `LEASE_SECONDS`). Claiming is refused while a test script runs, and
  starting a test releases every web-held line.
- **udev**
  - *Events* — live `udevadm monitor --kernel --udev --property` (filter by source, text; pause; click an
    event for its properties). The monitor process runs only while this view is polled and stops 10 s
    later (`core/udev.py`, `UdevMonitor`).
  - *Rules* — rules files of `/etc/udev/rules.d` (editable), `/run/udev/rules.d` and `/lib/udev/rules.d`
    (read-only, *Override in /etc* copies one into `/etc`). Overridden files are marked. *Check* runs a
    built-in syntax check (`udevadm verify` needs systemd ≥ 254); Save asks before writing a file with
    problems. Changes apply after *Reload rules*.
  - *Service & tools* — `systemd-udevd` status, restart, reload rules, `udevadm trigger` (by subsystem
    and/or device), `udevadm test`, attribute walk.

## Test log viewer (`/logs`)

Browses the run logs in `test_logs_dir` (`testLogs/`), written for every run started from the Tests page
(**Logs** in the top bar, or **Log viewer** on the Tests page).

- Filters: script, verdict (PASS / FAIL / ERROR / STOPPED, several at once), serial number or file name,
  date range, "failed at step". The filter is kept in the URL (`/logs#verdict=FAIL&q=SN-1`), so a view can be linked.
- Statistics over the filter: runs per verdict, yield (stopped runs excluded), distinct boards, first-pass yield
  (first finished run of each serial), top failing steps.
- Run list with first failure, 100 per page; click a serial to see every run of that board; CSV export.
- Log view: steps with status and a limit bar showing where the measured value lies between its limits,
  sections (stop-on-fail, finalization), operator prompts/answers, script output (can be hidden), raw text,
  search, ←/→ to move to the newer/older run.
- Step analysis (click a step name): every value of that step across the filtered runs, run chart with limits
  and mean, min / mean / max / σ / Cpk.

`core/test_logs.py` parses the log format of `core/test_runner.py` (fixed columns: name 40, condition 28, units)
and caches parsed files by mtime/size.

---

## Test Platform (`/tests`)

- Scripts: every `*_test.py` in `tests_dir` (default `testPlatform/`); the first line of the module docstring is
  shown as the description. Demo scripts (`demo_*_test.py`) need no hardware.
- A script runs as a child process (`python3 -u`, cwd = `tests_dir`, env `TEST_RUNNER=1`). Only one run at a time.
  Stdin receives one Enter and is closed, so interactive scripts run exactly one sequence.
- `testStrategy.TestStrategy` prints `@@RESULT {"name","condition","units","status"}` lines in runner mode;
  all other output is shown in the *Output* panel and written to the log.
- Verdict: `STOPPED` (Stop pressed: SIGINT, SIGKILL after 3 s), `ERROR` (any ERROR result, non-zero exit code,
  or no results), `FAIL` (any FAIL), otherwise `PASS`.
- Stop on fail + finalization: structure a script as `ts.run(steps, finalize)`. With the *Stop on fail* checkbox
  (checked by default; env `TEST_STOP_ON_FAIL=1`, or `--stop-on-fail` in a terminal) the first FAIL/ERROR skips the
  remaining steps. `finalize` (power off, relays to a safe state) always runs: after pass, fail, an exception or
  Stop (SIGINT; the runner waits 10 s before SIGKILL). Scripts without `ts.run()` are not affected.
  Separator rows (`ts.section(title)`) are shown in the results. Demo: `demo_stopfail_test.py`.
- Serial number: the *Serial number* field is passed to the script as `--sn <serial>` (letters, digits, `-_.`,
  up to 64 chars; empty = no argument). In a script: `ts.serial`. Enter in the field starts the test (barcode
  scanners); after a run the field is selected for the next unit. Demo: `demo_serial_test.py` (valid: `test`
  or `VTP-123456`).
- Logs: `test_logs_dir/<YYYYmmdd_HHMMSS>_<script>[__<serial>]_<VERDICT>.log` (`.running` while in progress).
  The *History* popup lists them (with serial) and can delete one log or all logs (the running log is kept).
- Board statistics (Test Run panel): PASS / FAIL / ERROR boards and yield for the selected script, counted from
  the logs (stopped runs excluded; clearing the history resets them). Step counters of the current run are shown
  under the results table.
- Operator input steps (`TestStrategy` methods; in a terminal they fall back to `input()`):

  | Method | Web UI | Returns |
  |---|---|---|
  | `askText(name, message, default="")` | text field (empty not accepted) | `str` |
  | `askNumber(name, message, lo=None, hi=None, units="", default=None)` | number field, range-checked | `float` |
  | `askChoice(name, message, options, default=None)` | drop-down | selected option |
  | `askButtons(name, message, buttons=("OK",))` | one button per option | pressed label |
  | `askYesNo(name, message)` | Yes / No buttons | `bool` |

  The script prints `@@PROMPT {json}` and blocks; the answer comes back as a JSON line on the pipe from
  `TEST_RUNNER_ANSWER_FD`. The answer is logged as an `INFO` step (does not affect the verdict); check it with
  the regular test methods. Demo: `demo_operator_test.py`.

## Installation

```bash
sudo bash setup.sh
```

The script performs:
1. `apt install python3-flask` and `apt-get install p7zip-full`
2. `setcap cap_net_bind_service=+ep` on Python3 (required for ports < 1024)
3. Creates and starts `/etc/systemd/system/systemmngmntservice.service`

### Service management

```bash
sudo systemctl status systemmngmntservice.service
sudo systemctl restart systemmngmntservice.service
journalctl -u systemmngmntservice.service -f
```

---

## Testing

The tests use only the standard library (`unittest`) and never touch the live service, `config.json`
or `testLogs/` (they work on temporary copies):

```bash
python3 -m unittest discover -s tests -t . -q          # whole suite, ~20 s
python3 -m unittest tests.test_access -q               # one module
```

| Module | Covers |
|---|---|
| `test_access.py` | access matrix: anonymous / logged in / auth disabled |
| `test_config.py` | legacy migration, per-host sections, save / reset |
| `test_monitor.py` | `/api/monitor` payload, sampler lease, active interface detection |
| `test_logs.py` | log parsing, filters, yield/FPY, step statistics, CSV, `/api/logs*` |
| `test_test_runner.py` | operator answer validation, real runs of the demo scripts, stop |
| `test_offline.py` | no external (CDN) URLs in templates/static, vendored libraries are served |
| `test_net.py`, `test_udev.py`, `test_shell.py` | CAN frame parsing, udev rule linter, path/command helpers |

Visual checks: `python3 tests/devserver.py` starts a second instance on port 5099 (login disabled in memory,
`?js=` hook for opening popups), `tests/screenshot.sh <path> <out.png>` takes a headless Chromium screenshot,
`tests/docs_screenshots.sh` regenerates the images in `docs/img`. See [tests/README.md](tests/README.md).

---

## Authentication

When `auth.enabled = true`:
- **anonymous visitors** see only the *Service Control* block for the target service (`service_name`) — no
  service selector and no *All Services* list — and may run the actions listed in `public_service_actions` on it;
  below it they see the read-only *System Monitor* dashboard;
- **logged-in users** get everything else (backups, system info, code editor, terminal, settings, video, power).

When `auth.enabled = false`, every visitor has full access.
Credentials are stored in `config.json` and can be changed via `/settings`.
