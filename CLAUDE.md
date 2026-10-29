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
  nav.py               NAV_ITEMS – top bar navigation registry
  web.py               template context for every page, asset() cache-busting helper
  test_runner.py       runs test-platform scripts, verdicts, per-run log files
routes/                one blueprint per feature; listed in routes/__init__.py BLUEPRINTS
templates/
  base.html            page skeleton: top bar, shared modals, shared scripts
  partials/            flash, services modal, video controls/modal, power menu
  <page>.html          extends base.html
static/
  css/base.css         tokens (CSS variables), reset, top bar, buttons, forms, cards, modal, table, badges, utils
  css/components.css   shared widgets: services, status log, sysinfo, video, power menu
  css/<page>.css       page-only styles
  js/core.js           App namespace (config, api, onEscape, formatters), esc(), toast()
  js/services.js       Services: selector, actions, modal, status colouring  (public)
  js/sysinfo.js        SysInfo: polling + render helpers                    (logged in)
  js/video.js          Video: device list + stream popup                    (logged in)
  js/power.js          power menu                                           (logged in)
  js/<page>.js         page-only logic
```

## Access model (must be preserved)
- **Anonymous**: main page with the *Service Control* card only, the *All Services* modal, `/api/services`,
  `/api/status`, and service actions listed in `config.public_service_actions` (default `["restart"]`).
- **Logged in**: everything else (backups, sysinfo, editor, terminal, settings, video, power, macros).
- `auth.enabled = false` ⇒ every visitor is treated as logged in.
- Backend is the source of truth: **every route is `@login_required` unless it is intentionally public**.
  Public routes are only the ones listed above plus `/login`, `/logout`, `/favicon.ico`, static files.
  Hiding a button in a template is never a substitute for the decorator.
- `login_required` returns JSON 401 for `/api/*` and non-GET requests, otherwise redirects to `/login?next=…`.
- Templates use `logged_in` and `can_service('restart')`; JS uses `App.config.loggedIn` and `Services.canAct()`.
  Scripts/markup for logged-in widgets are not rendered for anonymous users at all.

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
- Serial number from the UI reaches the script as `--sn <serial>` (validated by `SERIAL_PATTERN`); scripts read
  it via `ts.serial`. It is part of the log file name (`__<serial>`, see `LOG_PATTERN`) and the log header.
- Page: `routes/tests.py`, `templates/tests.html`, `static/js/tests.js`, `static/css/tests.css`.

## Adding a page
1. `routes/<name>.py`: `bp = Blueprint('<name>', __name__)`, view decorated with `@login_required`
   (or deliberately public), `return render_template('<name>.html', ...)`.
2. Add `<name>.bp` to `BLUEPRINTS` in `routes/__init__.py`.
3. `templates/<name>.html`:
   ```jinja
   {% extends 'base.html' %}
   {% block title %}My Page — {% endblock %}
   {% block page_name %}<span class="brand-sub"> — My Page</span>{% endblock %}
   {% block head %}<link rel="stylesheet" href="{{ asset('css/<name>.css') }}">{% endblock %}
   {% block content %}<main class="page"> … cards … </main>{% endblock %}
   {% block scripts %}<script src="{{ asset('js/<name>.js') }}"></script>{% endblock %}
   ```
   Other blocks: `topbar_tools` (page controls in the top bar), `modals`, `body_class`.
4. Add a `NavItem('<name>.<view>', 'Label', 'fa-solid fa-icon', public=False)` to `core/nav.py`.
5. Create `static/css/<name>.css` / `static/js/<name>.js` only if the page needs them.

## Adding an API endpoint
- Put it in the blueprint of its feature (or a new one), URL under `/api/...`, decorate with `@login_required`.
- State-changing endpoints use **POST** with a JSON body; read it with `request.get_json(silent=True) or {}`.
- Respond with `jsonify({...})`; errors as `jsonify({'error': msg}), <status>`.
- Read settings via `core.config` accessors (`config.target_dir()`, `config.get(key)`), never module constants.
- Shell: interpolate every argument through `quote()`; use `run_command()` for privileged commands,
  `sh()` for quiet read-only ones. File paths from the client must go through `resolve_inside(path, root)`.

## Front-end conventions
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
- `python3 -c "import app"` must succeed.
- Check the access matrix with Flask's test client: anonymous gets 200 on `/`, `/api/services`, `/api/status`,
  401 on other `/api/*`, 302 on protected pages; after `POST /login` everything returns 200.
- Visual check with headless Chromium against a test instance:
  `chromium --headless=new --no-sandbox --window-size=1400,950 --virtual-time-budget=6000 --screenshot=out.png http://127.0.0.1:5099/`
  (for logged-in views start the test instance with `config.CFG['auth']['enabled'] = False` set in memory).
- Update `README.md` (routes/API tables) when routes change.
