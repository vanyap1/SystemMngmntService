# SystemMngmntService

A web panel for remote monitoring and management of an application on a Linux server.  
Runs as a standalone systemd service, independent of the target application's state.

---

## Purpose

- Monitor and control a target systemd service (start / stop / restart)
- Create backups of the application directory, upload and deploy updates
- Edit application files directly in the browser
- Run test-platform sequences, watch PASS/FAIL live, keep a log per run
- View system information (CPU, RAM, network, disks)
- Configure all parameters through the web interface

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
│   ├── js/           # core.js, services.js, sysinfo.js, video.js, power.js, devices.js (shared), <page>.js
│   └── img/
├── testPlatform/     # Test platform: *_test.py sequences + hardware drivers (run from the Tests page)
├── testLogs/         # One log file per test run (git-ignored)
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
    Dashboard --> SysInfo[CPU / RAM / network / disks]
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
| GET | `/api/services` | public | All systemd services (JSON) |
| GET | `/api/status?name=` | public | `systemctl status` output |
| POST | `/api/service/<start\|stop\|restart>?name=` | public for `public_service_actions`, else login | Service action |
| GET | `/api/sysinfo` | login | CPU, RAM, network, disks (JSON) |
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
| GET | `/api/devices/dev/info?path=` | login | `udevadm info` properties of one node inside `/dev` |
| GET | `/api/devices/gpio` | login | GPIO chips and lines like `gpioinfo` (read-only, libgpiod v1/v2) |
| GET | `/api/devices/gpio/ctl?client=` | login | Lines held by a popup client with live values (also renews its lease) |
| POST | `/api/devices/gpio/ctl` | login | `{client, action: claim\|input\|output\|set\|release\|release_all, chip, offset, value}` |
| POST | `/api/settings` | login | Save settings |
| GET | `/api/tests/scripts` | login | Test scripts (`*_test.py` in `tests_dir`) |
| POST | `/api/tests/start` / `/api/tests/stop` | login | Start `{script, serial, stop_on_fail}` / stop the running one |
| GET | `/api/tests/status?run_id=&results_from=&output_from=` | login | Current run, incremental results, output and pending operator prompt |
| POST | `/api/tests/answer` | login | Answer the pending operator prompt `{run_id, prompt_id, value}` |
| GET | `/api/tests/logs`, `/api/tests/logs/<name>[?download=1]` | login | Run history / log file |
| POST | `/api/tests/logs/delete` | login | Delete `{name}` or `{all: true}` |
| GET | `/api/tests/stats?script=` | login | Board counts per verdict for a script |

---

## Devices popup

The **Devices** button in the top bar (logged in) opens a popup with two tabs:

- **/dev** — the device node tree (symlinks are not followed), group filter (serial, USB, video, I²C,
  SPI, GPIO, block, input, sound) and text filter. Clicking a node shows its `udevadm info` properties.
  With *Auto* on, the list refreshes every 2 s; new nodes are highlighted and added/removed devices
  are listed in the footer (plus a toast, except `/dev/pts`, `/dev/shm`).
- **GPIO** — every `/dev/gpiochip*` with its lines: offset, global sysfs number (`base + offset`), name,
  consumer, direction, active level, bias/drive flags. Lines are only queried, never requested, so the
  view does not disturb running tests. Changed lines are highlighted. Without the Python `gpiod`
  module the raw `gpioinfo` output is shown.
- **GPIO control** (same tab): *Claim* requests a free line "as is" (its state is not changed), then it can
  be switched IN/OUT, an output toggled 0/1, an input level is read every second. Lines are held only
  while the GPIO tab is open: switching the tab, closing the popup or the page releases them, and a client
  that stops polling loses them after 6 s (`core/gpio_ctl.py`, `LEASE_SECONDS`). Claiming is refused while
  a test script runs, and starting a test releases every web-held line.

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

## Authentication

When `auth.enabled = true`:
- **anonymous visitors** see only the *Service Control* block and the *All Services* list on the main page and may
  run the service actions listed in `public_service_actions`;
- **logged-in users** get everything else (backups, system info, code editor, terminal, settings, video, power).

When `auth.enabled = false`, every visitor has full access.
Credentials are stored in `config.json` and can be changed via `/settings`.
