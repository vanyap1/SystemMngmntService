# Tests

Standard-library `unittest`, no extra packages. Run from the project root:

```bash
python3 -m unittest discover -s tests -t . -q     # everything (~20 s); prints only failures + summary
python3 -m unittest tests.test_monitor -q         # one module
python3 -m unittest tests.test_access.Anonymous   # one class
```

## Safety

`tests/support.py` must be imported first (every test module does it). It imports the app, then redirects
`config.CONFIG_PATH` and `test_logs_dir` to a temporary directory and forces known credentials
(`test` / `test`, auth enabled). Tests therefore never modify `config.json`, never add files to `testLogs/`
and never touch the live `systemmngmntservice.service`. Keep it that way:

- no `systemctl` actions except on the target service as a normal user (`sudo -n` fails harmlessly);
- no writes to `/etc/udev/rules.d`, no CAN link changes, no GPIO claims on real lines;
- temporary files only under `support.TMP`.

## Layout

| File | What it checks |
|---|---|
| `support.py` | shared setup, `client(logged_in=False)` helper |
| `test_access.py` | access model from CLAUDE.md (anonymous / logged in / auth disabled) |
| `test_config.py` | `config.json` store: migration, per-host sections, update, reset |
| `test_monitor.py` | system monitor sampler, lease, default-route interface, `/api/monitor` |
| `test_logs.py` | test log viewer: parsing, filters, statistics, CSV, `/api/logs*` |
| `test_test_runner.py` | operator answer validation, demo script runs, stop while waiting |
| `test_net.py` | CAN frame parsing, interface name validation |
| `test_udev.py` | rule file names, rules linter |
| `test_offline.py` | no CDN/external URLs; vendored libraries present and served |
| `test_shell.py` | `resolve_inside`, `sh`, `run_command` |

## Visual checks

```bash
python3 tests/devserver.py &                  # port 5099, login disabled in memory (--logs testLogs: real run logs)
python3 tests/devserver.py --port 5098 --auth &   # anonymous view
tests/screenshot.sh / /tmp/x.png              # prints JS "Uncaught" errors to stderr
tests/screenshot.sh '/tests?js=MonitorFloat.open()' /tmp/x.png 1400x900 9000
tests/docs_screenshots.sh                     # regenerate docs/img (both servers running)
```

- `?js=<code>` runs after page load; URL-encode `+` as `%2B` (a bare `+` becomes a space and breaks the code).
- Wait for data with `setTimeout(..., 2500)` inside `js`; `--virtual-time-budget` (4th arg) must exceed it.
- Monitor charts only have history while someone polls `/api/monitor` (30 s lease).
- Stop servers by PID (`kill <pid>`); `pkill -f` with a pattern that also appears in your own command line
  kills your shell.

## Adding tests

One `test_<feature>.py` per feature, starting with `from tests.support import ...`. New route ⇒ add it to the
lists in `test_access.py` (public or protected). New pure logic (parsers, validators) ⇒ table-driven tests with
`subTest`. Anything needing hardware (GPIO lines, CAN adapter, udev writes) stays a manual check.
