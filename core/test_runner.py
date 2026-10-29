"""Runs test-platform scripts (``*_test.py`` in config tests_dir) as child processes.

Protocol with the scripts (see testPlatform/testStrategy.py), active when TEST_RUNNER=1:
  * ``@@RESULT {json}`` - a test step result;
  * ``@@PROMPT {json}`` - the script waits for operator input; the answer is written as a
    ``{"id": n, "value": ...}`` line to the pipe whose fd is in TEST_RUNNER_ANSWER_FD.
Every other output line is kept as raw output. Only one test runs at a time
(the fixture hardware is shared).
"""
import ast
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime

from core import config

RESULT_PREFIX = '@@RESULT '
PROMPT_PREFIX = '@@PROMPT '
PROMPT_TYPES = ('number', 'text', 'choice', 'buttons')
MAX_TEXT_ANSWER = 1000
SCRIPT_PATTERN = re.compile(r'^[\w\-]+_test\.py$')
# <YYYYmmdd_HHMMSS>_<script stem>[__<serial>]_<VERDICT>.log  (script stems always end with _test)
LOG_PATTERN = re.compile(r'^(\d{8}_\d{6})_(.+?_test)(?:__([\w\-.]+))?_(PASS|FAIL|ERROR|STOPPED)\.log$')
SERIAL_PATTERN = re.compile(r'^[\w\-.]{1,64}$')
ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
MAX_OUTPUT_LINES = 20000
STOP_GRACE_SECONDS = 10   # time for the script's finalization after Stop (SIGINT)

# INFO (operator input) and SECTION (separator row) do not affect the verdict
STATUSES = ('PASS', 'FAIL', 'ERROR', 'INFO', 'SECTION')


def _script_description(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            doc = ast.get_docstring(ast.parse(f.read()))
        return doc.strip().split('\n')[0] if doc else ''
    except Exception:
        return ''


def list_scripts():
    tests_dir = config.tests_dir()
    try:
        names = sorted(n for n in os.listdir(tests_dir) if SCRIPT_PATTERN.match(n))
    except OSError:
        return []
    return [{'name': n, 'description': _script_description(os.path.join(tests_dir, n))}
            for n in names]


def list_logs(limit=100):
    logs_dir = config.test_logs_dir()
    try:
        entries = [e for e in os.scandir(logs_dir) if e.is_file() and LOG_PATTERN.match(e.name)]
    except OSError:
        return []
    entries.sort(key=lambda e: e.name, reverse=True)
    logs = []
    for e in entries[:limit]:
        ts, script, serial, verdict = LOG_PATTERN.match(e.name).groups()
        logs.append({'name': e.name, 'script': script + '.py', 'serial': serial or '', 'verdict': verdict,
                     'started': datetime.strptime(ts, '%Y%m%d_%H%M%S').timestamp(),
                     'size': e.stat().st_size})
    return logs


def board_stats(script):
    """Finished boards per verdict for one script (stopped runs are not counted)."""
    stats = {s: 0 for s in ('PASS', 'FAIL', 'ERROR')}
    for log in list_logs(limit=None):
        if log['script'] == script and log['verdict'] in stats:
            stats[log['verdict']] += 1
    stats['total'] = sum(stats.values())
    return stats


def delete_logs(name=None):
    """Delete one finished log (by name) or all of them. Returns the number of deleted files."""
    logs_dir = config.test_logs_dir()
    names = [name] if name else [l['name'] for l in list_logs(limit=None)]
    deleted = 0
    for n in names:
        if not LOG_PATTERN.match(n or ''):
            continue
        try:
            os.remove(os.path.join(logs_dir, n))
            deleted += 1
        except FileNotFoundError:
            pass
    return deleted


class TestRun:
    def __init__(self, run_id, script, serial='', stop_on_fail=True):
        self.id = run_id
        self.script = script
        self.serial = serial
        self.stop_on_fail = stop_on_fail
        self.started = time.time()
        self.finished = None
        self.state = 'RUNNING'          # RUNNING | PASS | FAIL | ERROR | STOPPED
        self.results = []
        self.output = []
        self.returncode = None
        self.stop_requested = False
        self.log_name = None
        self.prompt = None              # pending operator prompt

    def counts(self):
        counts = {s: 0 for s in STATUSES}
        for r in self.results:
            counts[r['status']] = counts.get(r['status'], 0) + 1
        return counts

    def elapsed(self):
        return round((self.finished or time.time()) - self.started, 1)


class TestRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._log = None
        self._answer_w = None
        self.run = None
        self._next_id = 1

    # ── Public API ──
    def is_running(self):
        return self.run is not None and self.run.state == 'RUNNING'

    def start(self, script, serial='', stop_on_fail=True):
        """Start a script; a non-empty serial is passed to it as ``--sn <serial>``."""
        serial = (serial or '').strip()
        if serial and not SERIAL_PATTERN.match(serial):
            raise ValueError('Serial number: up to 64 letters, digits, "-", "_" or "."')
        if not SCRIPT_PATTERN.match(script or '') or script not in {s['name'] for s in list_scripts()}:
            raise ValueError(f'Unknown test script: {script}')
        with self._lock:
            if self.is_running():
                raise RuntimeError('A test is already running')
            run = TestRun(self._next_id, script, serial, bool(stop_on_fail))
            self._next_id += 1
            self._open_log(run)
            answer_r, answer_w = os.pipe()
            env = dict(os.environ, TEST_RUNNER='1', PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8',
                       TEST_RUNNER_ANSWER_FD=str(answer_r),
                       TEST_STOP_ON_FAIL='1' if run.stop_on_fail else '0')
            try:
                self._proc = subprocess.Popen(
                    [sys.executable, '-u', script] + (['--sn', serial] if serial else []), cwd=config.tests_dir(), env=env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    pass_fds=(answer_r,), start_new_session=True)
                self._answer_w = os.fdopen(answer_w, 'w', encoding='utf-8')
            except OSError as e:
                os.close(answer_w)
                self.run = run
                self._add_result(run, {'name': 'Start script', 'condition': str(e),
                                       'units': '', 'status': 'ERROR'})
                self._finish(run, None)
                return run
            finally:
                os.close(answer_r)
            self.run = run
        # Interactive scripts wait for Enter before a sequence: run exactly one, then EOF.
        try:
            self._proc.stdin.write(b'\n')
            self._proc.stdin.close()
        except OSError:
            pass
        threading.Thread(target=self._read_output, args=(run, self._proc), daemon=True).start()
        return run

    def stop(self):
        with self._lock:
            if not self.is_running() or not self._proc:
                return False
            run, proc = self.run, self._proc
            run.stop_requested = True
        self._signal(proc, signal.SIGINT)
        threading.Thread(target=self._kill_later, args=(proc,), daemon=True).start()
        return True

    def answer(self, run_id, prompt_id, value):
        """Validate the operator's answer and pass it to the waiting script."""
        with self._lock:
            run = self.run
            if not self.is_running() or run.id != run_id or not run.prompt \
                    or run.prompt['id'] != prompt_id:
                raise RuntimeError('This prompt is no longer active')
            value = self._validate_answer(run.prompt, value)
            try:
                self._answer_w.write(json.dumps({'id': prompt_id, 'value': value}) + '\n')
                self._answer_w.flush()
            except (OSError, ValueError, AttributeError):
                raise RuntimeError('The test script is not reading answers')
            run.prompt = None
        self._write_log(f"             > operator answer: {value}")
        return value

    @staticmethod
    def _validate_answer(prompt, value):
        kind = prompt['type']
        if kind == 'number':
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError('Enter a number')
            lo, hi = prompt.get('min'), prompt.get('max')
            if (lo is not None and number < lo) or (hi is not None and number > hi):
                raise ValueError(f'Allowed range: {lo if lo is not None else "-∞"} … {hi if hi is not None else "∞"}')
            return number
        if kind in ('choice', 'buttons'):
            if value not in prompt.get('options', []):
                raise ValueError('Select one of the options')
            return value
        text = str(value if value is not None else '').strip()
        if not text:
            raise ValueError('The answer cannot be empty')
        return text[:MAX_TEXT_ANSWER]

    def status(self, run_id=None, results_from=0, output_from=0):
        run = self.run
        if run is None:
            return {'run': None}
        if run_id != run.id:
            results_from = output_from = 0
        return {'run': {
            'id': run.id,
            'script': run.script,
            'serial': run.serial,
            'stop_on_fail': run.stop_on_fail,
            'state': run.state,
            'started': run.started,
            'elapsed': run.elapsed(),
            'counts': run.counts(),
            'returncode': run.returncode,
            'log': run.log_name,
            'prompt': run.prompt,
            'results_from': results_from,
            'results': run.results[results_from:],
            'output_from': output_from,
            'output': run.output[output_from:],
        }}

    # ── Internals ──
    @staticmethod
    def _signal(proc, sig):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def _kill_later(self, proc):
        try:
            proc.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._signal(proc, signal.SIGKILL)

    def _read_output(self, run, proc):
        for raw in proc.stdout:
            line = ANSI_RE.sub('', raw.decode('utf-8', errors='replace')).rstrip('\r\n')
            if line.startswith(PROMPT_PREFIX):
                prompt = self._parse_prompt(line[len(PROMPT_PREFIX):])
                if prompt:
                    run.prompt = prompt
                    self._write_log(f"             ? operator prompt [{prompt['type']}]: {prompt['message']}")
                    continue
            if line.startswith(RESULT_PREFIX):
                try:
                    record = json.loads(line[len(RESULT_PREFIX):])
                    self._add_result(run, {
                        'name':      str(record.get('name', '')),
                        'condition': str(record.get('condition', '')),
                        'units':     str(record.get('units', '')),
                        'status':    record.get('status') if record.get('status') in STATUSES else 'ERROR',
                    })
                    continue
                except ValueError:
                    pass
            self._add_output(run, line)
        self._finish(run, proc.wait())

    @staticmethod
    def _parse_prompt(text):
        try:
            p = json.loads(text)
        except ValueError:
            return None
        if not isinstance(p, dict) or p.get('type') not in PROMPT_TYPES or not isinstance(p.get('id'), int):
            return None
        prompt = {'id': p['id'], 'type': p['type'], 'name': str(p.get('name', '')),
                  'message': str(p.get('message', '')), 'units': str(p.get('units', ''))}
        if p['type'] in ('choice', 'buttons'):
            prompt['options'] = [str(o) for o in p.get('options') or []] or ['OK']
        for key in ('min', 'max'):
            if isinstance(p.get(key), (int, float)):
                prompt[key] = p[key]
        if p.get('default') is not None:
            prompt['default'] = p['default']
        return prompt

    def _add_result(self, run, record):
        record['t'] = round(time.time() - run.started, 2)
        record['index'] = sum(1 for r in run.results if r['status'] != 'SECTION') + 1
        run.results.append(record)
        if record['status'] == 'SECTION':
            self._write_log(f"{'':12} ---- {record['name']} ----")
            return
        self._write_log(f"[{record['t']:8.2f}s] {record['status']:<6} {record['name'][:40]:<40} "
                        f"{record['condition']:<28} {record['units']}".rstrip())

    def _add_output(self, run, line):
        if len(run.output) < MAX_OUTPUT_LINES:
            run.output.append(line)
        self._write_log('             | ' + line)

    def _finish(self, run, returncode):
        run.returncode = returncode
        run.prompt = None
        if self._answer_w:
            try:
                self._answer_w.close()
            except OSError:
                pass
            self._answer_w = None
        counts = run.counts()
        if run.stop_requested:
            run.state = 'STOPPED'
        else:
            if returncode not in (0, None):
                tail = next((l for l in reversed(run.output) if l.strip()), '')
                self._add_result(run, {'name': 'Script exit', 'units': '', 'status': 'ERROR',
                                       'condition': f'exit code {returncode}' + (f': {tail}' if tail else '')})
                counts = run.counts()
            elif not run.results:
                self._add_result(run, {'name': 'Script exit', 'units': '', 'status': 'ERROR',
                                       'condition': 'no test results reported'})
                counts = run.counts()
            run.state = 'ERROR' if counts['ERROR'] else 'FAIL' if counts['FAIL'] else 'PASS'
        run.finished = time.time()
        self._close_log(run)

    def _open_log(self, run):
        stamp = datetime.fromtimestamp(run.started).strftime('%Y%m%d_%H%M%S')
        logs_dir = config.test_logs_dir()
        serial_part = f"__{run.serial}" if run.serial else ''
        self._log_base = os.path.join(logs_dir, f"{stamp}_{os.path.splitext(run.script)[0]}{serial_part}")
        try:
            os.makedirs(logs_dir, exist_ok=True)
            self._log = open(self._log_base + '.running', 'w', encoding='utf-8')
        except OSError:
            self._log = None
            return
        self._write_log(f"Script:   {run.script}\n"
                        f"Serial:   {run.serial or '-'}\n"
                        f"Stop on fail: {'yes' if run.stop_on_fail else 'no'}\n"
                        f"Host:     {socket.gethostname()}\n"
                        f"Started:  {datetime.fromtimestamp(run.started):%Y-%m-%d %H:%M:%S}\n"
                        + '-' * 100)

    def _write_log(self, text):
        if self._log:
            self._log.write(text + '\n')
            self._log.flush()

    def _close_log(self, run):
        if not self._log:
            return
        c = run.counts()
        self._write_log('-' * 100 + '\n'
                        f"Finished: {datetime.fromtimestamp(run.finished):%Y-%m-%d %H:%M:%S}"
                        f"  ({run.elapsed()} s, exit code {run.returncode})\n"
                        f"Results:  {len(run.results)} total, {c['PASS']} pass, "
                        f"{c['FAIL']} fail, {c['ERROR']} error\n"
                        f"VERDICT:  {run.state}")
        self._log.close()
        self._log = None
        final = f"{self._log_base}_{run.state}.log"
        os.replace(self._log_base + '.running', final)
        run.log_name = os.path.basename(final)


runner = TestRunner()
