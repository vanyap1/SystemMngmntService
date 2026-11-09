# CLAUDE.md — rules for AI assistants working on this project

## Communication
- Talk to the user in **Ukrainian**.
- All code, comments, commit messages, docs inside the repo: **English**.

## Environment
- Work happens over **SSH on the target device** (OrangePi, aarch64, Debian, Python 3.11, Flask 3.x from apt).
- The panel itself runs as systemd unit `systemmngmntservice.service` (as root, port from `config.json`, usually 80),
  entry point `app.py`. It is the user's live tool — **do not restart/stop it, reboot, or touch the managed
  service (`service_name` in config) without asking.**
- To test changes, run a second instance on a free port instead:
  `python3 -c "from app import app; app.run(host='127.0.0.1', port=5099)"`
  (as a normal user `sudo -n` fails, so status output shows a sudo error — expected).
- `config.json` holds live settings and credentials; it is edited from the web UI. Don't commit changes to it
  unless asked. `.secret_key` is generated at first start and is git-ignored.

## Config (per host)
- `config.json` = `{"default": {...}, "hosts": {"<hostname>": {...}}}`. The same repo is deployed to several
  machines; each one is identified by `socket.gethostname()` (`config.HOSTNAME`).
- Effective config (`config.CFG`) = `BUILTIN_DEFAULTS` ← `default` ← `hosts[HOSTNAME]` (deep merge).
  A host without a section runs on defaults; saving settings writes the full set of `HOST_KEYS` into
  `hosts[HOSTNAME]` only. `reset_host()` removes the section. `default` is edited by hand.
- A legacy flat config is migrated automatically on load (its values become this host's section and the defaults).
- New setting: add it to `BUILTIN_DEFAULTS`, to `EDITABLE_KEYS` (or `HOST_KEYS`) if it is editable,
  to `templates/settings.html` + `static/js/settings.js`, and expose an accessor in `core/config.py`.

## Layout
```
app.py                 create_app(): registers blueprints, runs the server
core/
  config.py            config.json store (defaults + per-host sections); read via accessors
  auth.py              is_logged_in(), login_required, can_service_action(), safe_next()
  shell.py             run_command() (sudo -n), sh() (quiet), quote(), resolve_inside()
  nav.py               SECTIONS – top bar sections and their pages (sub-tabs), SETTINGS
  updates.py           panel self-update: background fetch of the panel upstream, pull --ff-only, own-unit restart
  web.py               template context for every page, asset() cache-busting helper
  test_runner.py       runs test-platform scripts, verdicts, per-run log files
  test_logs.py         test log viewer: parse testLogs/*.log (cached), filters, yield/FPY, step stats, CSV
  gpio_ctl.py          manual GPIO control for the HW Utils popup: per-client claimed lines under a lease
  i2c.py               I²C tools for HW Utils: scan (i2cdetect), register read/write (i2ctransfer), labels
  net.py               interfaces/routes (ip -j), CAN link config, CanBus (raw socket, cyclic send, lease)
  udev.py              udev db grouping, USB/PCI/I2C buses, rules files + lint, UdevMonitor (lease)
  monitor.py           system monitor sampler (CPU/RAM/temp/active iface/disk I/O, 15 min history, lease)
  terminal.py          interactive shell in a pty for the editor's Terminal tab (SSE output, POST keys, lease)
  spawn.py             popen() with PDEATHSIG from one long-lived thread (children die with the panel only)
  pyrun.py             run / debug a .py from the editor: pty session, output buffer, lease, gentle stop
  pydbg_agent.py       bdb debugger running inside the debugged process (stdlib only), JSON over two pipes
  help_docs.py         documentation store: Markdown pages in help_dir, img/ + docs/ assets, search, .trash
  git_ops.py           git for target_dir / panel / help_dir repos: status, actions, problems + fixes (runs as repo owner)
  credentials.py       host secrets (git token) in ~/.config/systemmngmntservice/credentials.json — outside repos
  diagrams.py          diagram store: help_dir/diagrams/<name>.json + exported <name>.svg, rename relinks pages
routes/                one blueprint per feature; listed in routes/__init__.py BLUEPRINTS
templates/
  base.html            page skeleton: top bar, shared modals, shared scripts
  partials/            flash, services modal, video controls/modal, devices modal, power menu, update button, monitor_float
  <page>.html          extends base.html
help/                  documentation (user content): *.md pages, img/, docs/ attachments, examples/ raw notes
tests/                 unittest suite (support.py isolates config/logs), devserver.py, screenshot.sh
install.sh             installer: menu, online/offline install, service unit, `bundle` → tools/offline_bundle.py
tools/offline_bundle.py  builds offline bundles (local apt repo + Flask wheels) for armhf (H3) / arm64 (H5)
docs/img/              README screenshots
static/
  vendor/              Font Awesome 6.5.1, Monaco 0.44.0, xterm 5.3.0 (+fit), marked 12, DOMPurify 3, highlight.js 11
                       — local copies, see vendor/README.md
  css/base.css         tokens (CSS variables), reset, top bar, buttons, forms, cards, modal, table, badges, utils
  css/components.css   shared widgets: services, status log, sysinfo, video, power menu
  css/<page>.css       page-only styles
  js/core.js           App namespace (config, api, onEscape, formatters), esc(), toast()
  js/services.js       Services: selector, actions, modal, status colouring  (public)
  js/sysinfo.js        SysInfo: polling + render helpers                    (logged in)
  js/monitor.js        MonitorData (shared poller), TimeChart (canvas), Monitor.create(el), MonitorFloat (logged in)
  js/video.js          Video: device list + stream popup                    (logged in)
  js/power.js          power menu (reboot, shutdown, logout)                (logged in)
  js/updates.js        panel update button + popup                          (logged in)
  js/devices.js        HW Utils popup shell: tab registry, info panel, text popup (logged in)
  js/devices_<tab>.js  popup tabs: nodes (Devices + /dev), buses, net, gpio, i2c, udev — Devices.register({...})
  js/<page>.js         page-only logic
```

## Access model (must be preserved)
- **Anonymous**: main page with the *Service Control* card for the **target service only** (`service_name`;
  no selector, no *All Services* modal/button). `/api/services` returns only that service, `/api/status` and
  `/api/service/<action>` ignore `name` and use it; actions limited to `config.public_service_actions`
  (default `["restart"]`). Below it the read-only *System Monitor* card (`/api/monitor` is public);
  the floating Monitor window on other pages is logged-in only.
- **Logged in**: everything else (backups, sysinfo, editor, terminal, settings, video, devices/GPIO, power, macros).
- `auth.enabled = false` ⇒ every visitor is treated as logged in.
- Backend is the source of truth: **every route is `@login_required` unless it is intentionally public**.
  Public routes are only the ones listed above plus `/login`, `/logout`, `/favicon.ico`, static files.
  Hiding a button in a template is never a substitute for the decorator.
- `login_required` returns JSON 401 for `/api/*` and non-GET requests, otherwise redirects to `/login?next=…`.
- Templates use `logged_in` and `can_service('restart')`; JS uses `App.config.loggedIn` and `Services.canAct()`.
  Scripts/markup for logged-in widgets are not rendered for anonymous users at all.

## GPIO control (HW Utils popup)
- Lines are requested **only** on explicit Claim and only while the GPIO tab is open; every exit path
  (tab switch, popup close, `pagehide` beacon, lease timeout) must release them. Never hold lines otherwise.
- Claim requests "as is" (no state change). Claiming is refused while a test runs; `/api/tests/start`
  calls `gpio_ctl.release_all()` so scripts get the fixture lines.

## System monitor
- Main page: `Monitor.create(#mon-card)`; other pages: `MonitorFloat` window (`partials/monitor_float.html`,
  not rendered on `dashboard.index`). Both use one `MonitorData` poller of `/api/monitor?since=`.
- Charts follow one rule: one y-axis per chart (CPU %, RAM %, network rate) — never mix units in a chart.
  Colours only from CSS variables; TX is dashed so RX/TX differ without colour.
- The sampler thread (`core/monitor.py`) lives only while polled (30 s lease); keep it to cheap /proc and /sys
  reads — subprocesses (`lsblk`, `ip`) run per request and are cached.

## HW Utils popup (formerly "Devices"; the JS object and ids are still `Devices` / `devices_*`)
- Routes: `routes/devices.py` (devices, buses, GPIO), `routes/udev.py` (service, events, rules, udevadm tools),
  `routes/net.py` (interfaces, CAN), `routes/i2c.py` (I²C tools, `core/i2c.py`). Only CAN links may be reconfigured — never touch other interfaces (SSH/web).
- CAN without hardware: test in a user+net namespace with vcan:
  `unshare -rnm sh -c 'mount -t sysfs sysfs /sys; ip link set lo up; ip link add vcan0 type vcan; ip link set vcan0 up; …'`.
- New tab: a button in `partials/devices_modal.html` (`data-tab`), a `<section class="dev-pane" id="devpane-<id>">`
  (`.dev-toolbar` + `.dev-scroll`), and `static/js/devices_<id>.js` calling `Devices.register({id, autoMs, load,
  render, onShow, onHide, canLeave})`, included in `base.html`. Pass `this.id` to `Devices.summary()`.
- Background resources (GPIO lines, `udevadm monitor`) live only while their view is open and polled
  (lease on the server); every exit path must release them. Long-lived child processes are started with
  `core/spawn.py` `popen()` (PDEATHSIG fires when the *forking thread* exits — never fork them from a request thread).
- Rules are written only to `/etc/udev/rules.d` (names `^[\w.@+-]+\.rules$`); system dirs are read-only.
  Never scan I²C buses or open device nodes just to list them: the I²C tab touches a bus only on Scan / Read /
  Write (POST, explicit user action), locked while a test runs. Arguments are validated in `core/i2c.py`
  before `i2cdetect` / `i2ctransfer` run. Tests and `tests/devserver.py --fake-i2c` use the simulated bus in
  `tests/fake_i2c.py` — never probe the real buses of this board in tests (i2c-0 holds the PMIC).

## Test platform
- `testPlatform/` holds the user's hardware test sequences (GPIO relays via gpiod, stm8flash, UART, DMM) copied
  from the real fixture PC (nanopiduo2). This machine has no fixture: `uut_test.py`/`gpio_test.py` end in ERROR
  here — use `demo_*_test.py` to test the UI. Don't change hardware logic in those scripts without asking.
- `core/test_runner.py` runs `*_test.py` as a subprocess and parses `@@RESULT {json}` lines emitted by
  `testStrategy.py` when `TEST_RUNNER=1`. Results must always go through `TestStrategy` methods.
  Console behaviour of the scripts (SSH use) must stay unchanged.
- New test script: `<name>_test.py` in `tests_dir`, module docstring = description, use `TestStrategy`,
  run one sequence and exit (an `input()` prompt gets one Enter, then EOF).
- Operator input: only via `TestStrategy.askText/askNumber/askChoice/askButtons/askYesNo` — never `input()`
  (stdin is closed after one Enter). Protocol: `@@PROMPT {id,type,name,message,options,min,max,units,default}`
  on stdout, answer `{"id","value"}` on the pipe fd `TEST_RUNNER_ANSWER_FD`; the runner validates the value
  (`TestRunner._validate_answer`) before passing it on. New prompt type ⇒ update `PROMPT_TYPES`,
  `_parse_prompt`, `_validate_answer`, `Tests._promptField` (tests.js) and the console fallback in testStrategy.py.
- Result statuses: PASS / FAIL / ERROR affect the verdict; INFO (operator answers) and SECTION (separator rows)
  do not.
- Scripts use `ts.run(steps, finalize)`: `finalize` must bring the fixture to a safe state and always runs (pass,
  stop-on-fail, exception, Stop). Stop-on-fail is implemented in `testStrategy._print_result` (raises
  `StopOnFail` only while `run()` executes the steps), enabled by `TEST_STOP_ON_FAIL=1` from the runner.
- Background checks (emergency stop, interlocks): `testPlatform/testWatch.py` `TestWatch` passed to
  `ts.run(steps, finalize, watch=w)`. A failing check is delivered to the main thread as SIGINT → `AbortTest`
  (ERROR row, steps skipped, finalize runs; the watch is stopped before finalize). A real SIGINT without a pending
  abort stays a KeyboardInterrupt (Stop button). Tests: `tests/test_watch.py` (subprocesses), `demo_estop_test.py`.
- Instrument drivers live in the package `testPlatform/instruments/` (`psu.py`, `dmm.py`, `dmm2.py`, `adc.py`,
  `stm8_flash.py`, `uut_serial.py`); scripts import them as `from instruments.psu import PSU`. Firmware images and
  other binaries are in `testPlatform/instruments/fw/` — reach them via `instruments.FW_DIR` / `fw_path()` (the
  STM8 flasher defaults to it), never via a path relative to the working directory. The framework
  (`testStrategy.py`, `testWatch.py`) and the `*_test.py` scripts stay in `testPlatform/`. `psu.py`: SCPI PSU,
  raw TCP :8080, one connection per command, `ERROR…` → `PsuError`; tests use a fake server, never the real bench;
  its public methods must be in `help/testing/psu.md`. `demo_pass_test.py` uses the real PSU — tests don't run it.
- Serial number from the UI reaches the script as `--sn <serial>` (validated by `SERIAL_PATTERN`); scripts read
  it via `ts.serial`. It is part of the log file name (`__<serial>`, see `LOG_PATTERN`) and the log header.
- Page: `routes/tests.py`, `templates/tests.html`, `static/js/tests.js`, `static/css/tests.css`.
- Log viewer: `core/test_logs.py` (parser + cache, filters, statistics), `routes/logs.py`, `templates/logs.html`,
  `static/js/logs.js`, `static/css/logs.css`. It parses the text format written by `TestRunner._add_result` /
  `_open_log` / `_close_log` — if that format changes, update the parser and `tests/test_logs.py` together.

## Documentation (Docs page)
- `core/help_docs.py` + `routes/help.py` + `templates/help.html` + `static/js/help.js` + `static/css/help.css`,
  tests in `tests/test_help.py` (support.py points `help_dir` to a temp dir). Login only, including `/help/file/…`.
- Page paths are relative to `help_dir` and validated by `check_doc_path` (no `..`, hidden or reserved top-level
  folders `img`, `docs`, `examples`; max 3 folder levels). Assets: uploads get `safe_file_name`, images only with
  image extensions. Delete/remove = move to `help_dir/.trash`, never `os.remove`.
- Links inside pages stay **relative to the page** (portable Markdown); the front end resolves them
  (`Help._resolve`) to `/help/file/<path>` or `?doc=`. `rename_doc` rewrites `img/`/`docs/` links (`relink`).
- Rendered HTML always goes through DOMPurify; served files get a sandbox CSP (`_RAW_HEADERS`).
- `help/examples/` holds the user's raw notes — source material, do not edit or serve it as pages.
- Diagram editor lives **only inside the Docs page** (no own page/nav item): `#dg-pane` in `help.html`,
  `static/js/diagrams.js` (editor) + `static/js/diagram_render.js` (model → SVG, the model is documented at its top),
  API `/api/help/diagram*` in `routes/help.py`, store `core/diagrams.py`. The renderer is the single source of the
  SVG look: the editor shows `renderItems(..., {editor: true})`, saving uploads `toSvg()`. Keep `kinds` key order
  (legend order): the diagram GET avoids `jsonify` (it sorts keys).
- Test equipment library: a diagram whose `unit` item has `master: true` is a library component (categories and port
  types: `CATEGORIES` / `PORT_TYPES` in diagram_render.js, typical ports: `UNIT_TEMPLATES` in diagrams.js). Other
  diagrams place it as `unit` with `ref` and a **copy** of category/title/ports (exports stay self-contained); the
  editor compares the copy on open (`checkUnits`) and offers *Update*. Wire ends on units are `{id, port}` — when
  ports disappear, wires are detached (`_detachMissing`), never dropped. `rename` relinks `ref`s (`_relink_units`).
  Catalogs (sidebar groups station / assembly / bus / component / uut / diagram; `bus` = symbol with `detail: "bus"`) are virtual: `doc.catalog` or derived by
  `DiagramRender.catalogOf` = `core/diagrams.catalog()` (keep both rules equal, tested in tests/test_help.py);
  files stay flat in help/diagrams — never move them into folders (links and `ref`s use the bare name).
  Wire colour without `color` = `DiagramRender.wireColor` (start port type → end port type → tapped bus); ports adopt
  the colour of their wire (`portColors`). Signal wires may end on a bus `{wire, t}`; bus ends never tap (no recursion) —
  every place that moves/copies/deletes wire ends must treat taps as attached (`Diagrams._attached`).
  Visual checks without touching help/: `python3 tests/devserver.py --help-dir <scratch>`.

## Git (Settings → Git, popup in editor / docs)
- `core/git_ops.py` + `routes/git.py` + `static/js/git.js` (one `Git` panel: `Git.mount(el, repo)` on Settings,
  `Git.openModal(repo)` with `partials/git_modal.html`; toolbar icons use `data-git-badge="<repo>"`), styles in
  `components.css`, tests `tests/test_git.py` (temporary repos only — never run git actions on the real repo in tests).
- Repos inside target_dir (cloned projects) are found by `scan_target()` and addressed as `dir:<rel>`; `resolve()`
  confines them to target_dir and requires a `.git`. Editor integration: `static/js/editor_git.js` (`EditorGit`,
  tree marks from `/api/git/tree_status`, refreshed on tree load, save and the `git-changed` DOM event that `Git`
  fires after every action). From editor.js reach it with `typeof EditorGit !== 'undefined'` (`const` is not on window).
  Visual checks with another target_dir: `python3 tests/devserver.py --target DIR`.
- Git always runs through `git_ops._run_raw` (as the repo owner, `GIT_TERMINAL_PROMPT=0`, timeouts). Paths from the
  client must pass `check_paths` (current status list), branch names `check_branch`; keep `--` before paths.
- **The token must never reach a repository or the browser**: only `core/credentials.py` stores it (outside repos,
  0600, never in config.json); pass it only via `token=` (one-shot credential helper + env); run every text shown to
  the user through `scrub()`; `credentials.public()` is the only thing returned. Destructive actions create a
  backup first (`Repo.backup()`). New problem ⇒ `Repo.problems()` + its fix in `Repo.fix()` + a test.

## Installer
- `install.sh` is the only installer (`setup.sh`/`setup_offline.sh` just call it). Steps must stay idempotent and
  never restart the running panel without a confirmation (`--yes` for scripts). Tests: `tests/test_install.py`.
- New runtime dependency ⇒ add the Debian package to a component in **both** `PKGS` (install.sh) and
  `COMPONENTS` (tools/offline_bundle.py) — the test checks they match; pure-Python packages go to `WHEELS` (both).
- The offline path must work without Python (parse `manifest.json` with sed) and without network: apt reads the
  bundle as `deb [trusted=yes] file:…/debs ./` with private lists/cache. Bundles live in git-ignored `setup_data/`.

## Top bar
- Layout: brand · `.tb-sections` (core/nav.py) · `.tb-page` (block `topbar_tools`) · `.tb-tools` (Video, Monitor,
  Devices, Services, Settings) · power menu (+ Logout) · update button. Labels in `.tb-label` hide on narrow screens.
- The update check (`core/updates.py`) runs only while the UI polls `/api/update/status`, at most every
  `update_check_minutes`; tests and `tests/devserver.py` set it to 0 (`devserver.py --fake-update` shows the button).
  Never fetch or pull the real repository in tests — point `config.BASE_DIR` to a temporary clone (`tests/test_updates.py`).

## Run / debug Python (code editor)
- `static/js/editor_debug.js` (`PyDebug`) ↔ `routes/pyrun.py` ↔ `core/pyrun.py` (session) ↔ `core/pydbg_agent.py`
  (inside the child, started via `python3 -c` so `__main__` can be replaced; it must import only the stdlib and
  removes its own folder from `sys.path`). Tests: `tests/test_pyrun.py` (temporary target_dir).
- The script runs in a pty (console behaviour like SSH); terminal input goes to it while a session is active.
- One session; lives while polled (`LEASE_SECONDS`), page close sends a stop beacon, child has PDEATHSIG.
  Stop = debugger quit / SIGINT first (finally/finalize must run), then SIGTERM, SIGKILL.
- Mutually exclusive with the test runner (`pyrun.blocked`, check in `/api/tests/start`); start releases GPIO.
- Hover evaluation accepts only names / attributes / constant subscripts (`hover_safe`) — never calls code.

## Terminal (code editor)
- `core/terminal.py` + `routes/terminal.py` + `static/js/web_terminal.js` (`WebTerm`): a login shell in a pty,
  output as Server-Sent Events with byte offsets (reconnect resumes), keys as batched POSTs (order kept), resize via
  TIOCSWINSZ. No websockets (offline, Flask dev server). Runs as the owner of target_dir via `spawn.popen`
  (user/group/extra_groups); closed IDLE_SECONDS after the last stream; max MAX_SESSIONS. Tests: `tests/test_terminal.py`.
- Page shortcuts must not steal keys inside `.xterm` (mc uses F-keys, Ctrl+key). The *Run* tab is the console of
  `PyDebug` (its keys go to the script's pty via `/api/pyrun/input`). Macros type into the shell (`WebTerm.run`).
- Headless screenshots: a page with an open EventSource never idles, so `--virtual-time-budget` hangs; drive such
  pages with real waits (Chrome DevTools protocol) instead.

## Documentation window in the editor
- `static/js/help_float.js` (`HelpFloat`), markup in `templates/editor.html`, styles in `editor.css`; it reads the
  same docs via `/api/help/tree` + `/api/help/doc` and renders like the Docs page (marked → DOMPurify, hljs per line).
- `help/testing/test-platform.md` documents `TestStrategy`: a new public method must be described there
  (`tests/test_docs_content.py` checks it, and that every relative link / image in `help/` exists).

## Code editor file tree
- `/api/tree?path=` returns **one folder**; the front end loads folders when opened and remembers open ones
  (`localStorage`). Never walk target_dir recursively on the server — it may hold big mounted disks.
  `git_ops.scan_target()` stays on target_dir's filesystem, has a time budget and a short cache.

## Adding a page
1. `routes/<name>.py`: `bp = Blueprint('<name>', __name__)`, view decorated with `@login_required`
   (or deliberately public), `return render_template('<name>.html', ...)`.
2. Add `<name>.bp` to `BLUEPRINTS` in `routes/__init__.py`.
3. `templates/<name>.html`:
   ```jinja
   {% extends 'base.html' %}
   {% block title %}My Page — {% endblock %}
   {% block head %}<link rel="stylesheet" href="{{ asset('css/<name>.css') }}">{% endblock %}
   {% block content %}<main class="page"> … cards … </main>{% endblock %}
   {% block scripts %}<script src="{{ asset('js/<name>.js') }}"></script>{% endblock %}
   ```
   Other blocks: `topbar_tools` (page controls in the top bar), `modals`, `body_class`.
4. Add a `NavItem('<name>.<view>', 'Label', 'fa-solid fa-icon', public=False)` to a section's pages in `core/nav.py`
   (a section with several pages shows them as sub-tabs, like Tests → Run / Logs), or a new `Section` for a new
   area of work. Global tools (popups, Settings, power) are not sections — they go into `.tb-tools` in base.html.
5. Create `static/css/<name>.css` / `static/js/<name>.js` only if the page needs them.

## Adding an API endpoint
- Put it in the blueprint of its feature (or a new one), URL under `/api/...`, decorate with `@login_required`.
- State-changing endpoints use **POST** with a JSON body; read it with `request.get_json(silent=True) or {}`.
- Respond with `jsonify({...})`; errors as `jsonify({'error': msg}), <status>`.
- Read settings via `core.config` accessors (`config.target_dir()`, `config.get(key)`), never module constants.
- Shell: interpolate every argument through `quote()`; use `run_command()` for privileged commands,
  `sh()` for quiet read-only ones. File paths from the client must go through `resolve_inside(path, root)`.

## Front-end conventions
- **Offline only**: the panel runs in closed networks. Never link CDNs/external URLs (scripts, styles, fonts,
  images); put third-party files into `static/vendor/<lib>/` with their license and list them in
  `static/vendor/README.md`. `tests/test_offline.py` enforces this.
- No Bootstrap, no inline `<style>` blocks in pages (tiny page-local styles in `{% block head %}` are the
  exception, e.g. login). Reuse classes from `base.css`/`components.css` before adding new ones:
  layout `.page .grid .grid-main-side .stack .row .spacer`, cards `.card .card-head .card-body`,
  buttons `.btn` + `.btn-primary|success|danger|warning|info|ghost|nav|start|stop|restart` (`.btn-sm|lg|block`),
  forms `.field .input .select-mono .hint .field-row .check-row`, tables `.tbl`, `.badge-*`,
  modals `.modal-overlay(.open) > .modal-box > .modal-head/.modal-body/.modal-foot`, text `.muted .text-ok .text-error`.
- Colours come from CSS variables in `base.css` (`--accent`, `--danger`, `--code`, …); don't hardcode new ones.
- JS: use `App.api(url, {json})` (handles JSON/text, errors, 401 → login), `esc()` for every value inserted
  into HTML, `toast(msg, isError)`, `App.onEscape(fn)` for closing popups. Pass values into inline handlers as
  `esc(JSON.stringify(value))`. Group page logic in one object (`const MyPage = {...}`), like `Dashboard`.
- Server data for JS goes through `window.APP_CONFIG` (built in `core/web.py`) or an API call — never
  Jinja inside `.js` files.
- Link static files with `{{ asset('path') }}` (adds a cache-busting version).

## Verification before finishing
Use the test suite instead of ad-hoc scripts — it is fast, quiet and saves tokens (see `tests/README.md`):
- `python3 -m unittest discover -s tests -t . -q` must pass (prints only failures; ~20 s). While iterating,
  run just the relevant module (`python3 -m unittest tests.test_<feature> -q`).
- New/changed route ⇒ update the URL lists in `tests/test_access.py`; new feature ⇒ add `tests/test_<feature>.py`
  (import `tests.support` first — it isolates `config.json` and `testLogs/`).
- UI changes: `python3 tests/devserver.py &` (port 5099, login off; `--auth` for the anonymous view), then
  `tests/screenshot.sh '<path>[?js=…]' <scratch>/x.png [WxH] [budget_ms] [port]` — it also prints JS errors.
  Look at screenshots only when layout matters; crop with PIL to the area you changed. Kill the server by PID.
- README screenshots: `tests/docs_screenshots.sh` (regenerates `docs/img`).
- Update `README.md` (routes/API tables) when routes change.
