"""Test run logs (testLogs/*.log written by core.test_runner): parsing, filtering, statistics.

Parsed logs are cached by (mtime, size), so listing thousands of files stays cheap after the first scan.
"""
import csv
import io
import os
import re
import statistics
from collections import Counter
from datetime import datetime

from core import config
from core.test_runner import LOG_PATTERN

VERDICTS = ('PASS', 'FAIL', 'ERROR', 'STOPPED')
STEP_RE = re.compile(r'^\[\s*([\d.]+)s\] (\w+)\s+(.*)$')
SECTION_RE = re.compile(r'^\s{12} ---- (.*) ----$')
HEADER_RE = re.compile(r'^([\w ]+):\s+(.*)$')
FINISHED_RE = re.compile(r'^Finished: (\S+ \S+)\s+\(([\d.]+) s, exit code (-?\d+|None)\)')
LIMITS_RE = re.compile(r'^\s*(-?[\d.eE+]+)\s*<\s*(-?[\d.eE+]+)\s*<\s*(-?[\d.eE+]+)\s*$')
NAME_WIDTH, COND_WIDTH = 40, 28            # column widths used by TestRunner._add_result

_cache = {}                                # name -> (mtime_ns, size, parsed)


def _split_step(rest):
    """'<name:40> <condition:28> <units>' -> (name, condition, units).

    Units are a short word after column 28; a longer condition simply runs on (no units then).
    """
    name = rest[:NAME_WIDTH].rstrip()
    tail = rest[NAME_WIDTH + 1:]
    units = tail[COND_WIDTH + 1:].strip()
    if len(tail) > COND_WIDTH + 1 and tail[COND_WIDTH] == ' ' and units and ' ' not in units and len(units) <= 12:
        return name, tail[:COND_WIDTH].rstrip(), units
    return name, tail.strip(), ''


def measurement(condition):
    """'lo < value < hi' -> (lo, value, hi) floats, else None."""
    m = LIMITS_RE.match(condition or '')
    if not m:
        return None
    try:
        return tuple(float(x) for x in m.groups())
    except ValueError:
        return None


def parse_text(text):
    """Parse a log file into header, ordered items (steps, sections, output, prompts) and footer."""
    header, footer, items = {}, {}, []
    part = 0                                # 0 header, 1 body, 2 footer
    for line in text.split('\n'):
        if line.startswith('-' * 100):
            part += 1
            continue
        if part == 0:
            m = HEADER_RE.match(line)
            if m:
                header[m.group(1).strip().lower().replace(' ', '_')] = m.group(2).strip()
            continue
        if part >= 2:
            m = FINISHED_RE.match(line)
            if m:
                footer.update(finished=m.group(1), duration=float(m.group(2)), exit_code=m.group(3))
            elif line.startswith('VERDICT:'):
                footer['verdict'] = line.split(':', 1)[1].strip()
            continue
        m = STEP_RE.match(line)
        if m:
            name, cond, units = _split_step(m.group(3))
            items.append({'type': 'step', 't': float(m.group(1)), 'status': m.group(2),
                          'name': name, 'condition': cond, 'units': units})
            continue
        m = SECTION_RE.match(line)
        if m:
            items.append({'type': 'section', 'name': m.group(1)})
            continue
        body = line[13:] if line.startswith(' ' * 13) else line
        if body.startswith('| '):
            items.append({'type': 'output', 'text': body[2:]})
        elif body.startswith('? operator prompt'):
            items.append({'type': 'prompt', 'text': body.split(':', 1)[1].strip() if ':' in body else body})
        elif body.startswith('> operator answer:'):
            items.append({'type': 'answer', 'text': body.split(':', 1)[1].strip()})
        elif line.strip():
            items.append({'type': 'output', 'text': line})
    steps = [i for i in items if i['type'] == 'step']
    counts = Counter(s['status'] for s in steps)
    first_fail = next((s for s in steps if s['status'] in ('FAIL', 'ERROR')), None)
    return {'header': header, 'footer': footer, 'items': items,
            'counts': {k: counts.get(k, 0) for k in ('PASS', 'FAIL', 'ERROR', 'INFO')},
            'first_fail': {'name': first_fail['name'], 'condition': first_fail['condition'],
                           'status': first_fail['status']} if first_fail else None}


def _path(name):
    return os.path.join(config.test_logs_dir(), name)


def parse(name):
    """Parsed log by file name (cached); None if the name is invalid or the file is gone."""
    if not LOG_PATTERN.match(name or ''):
        return None
    path = _path(name)
    try:
        st = os.stat(path)
    except OSError:
        _cache.pop(name, None)
        return None
    hit = _cache.get(name)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        parsed = parse_text(f.read())
    ts, script, serial, verdict = LOG_PATTERN.match(name).groups()
    parsed.update(name=name, script=script + '.py', serial=serial or '', verdict=verdict,
                  started=datetime.strptime(ts, '%Y%m%d_%H%M%S').timestamp(), size=st.st_size)
    _cache[name] = (st.st_mtime_ns, st.st_size, parsed)
    return parsed


def all_names():
    try:
        return sorted((e.name for e in os.scandir(config.test_logs_dir())
                       if e.is_file() and LOG_PATTERN.match(e.name)), reverse=True)
    except OSError:
        return []


def _day(value, end=False):
    try:
        d = datetime.strptime(value, '%Y-%m-%d')
    except (TypeError, ValueError):
        return None
    return d.timestamp() + (86400 if end else 0)


def query(script='', verdict='', q='', date_from='', date_to='', step=''):
    """Logs (newest first) matching the filters; `q` matches serial or file name, `step` a failed step."""
    verdicts = {v for v in (verdict or '').upper().split(',') if v in VERDICTS}
    q = (q or '').strip().lower()
    t0, t1 = _day(date_from), _day(date_to, end=True)
    out = []
    for name in all_names():
        m = LOG_PATTERN.match(name)
        ts, scr, serial, ver = m.groups()
        if script and scr + '.py' != script:
            continue
        if verdicts and ver not in verdicts:
            continue
        if q and q not in (serial or '').lower() and q not in name.lower():
            continue
        started = datetime.strptime(ts, '%Y%m%d_%H%M%S').timestamp()
        if (t0 and started < t0) or (t1 and started >= t1):
            continue
        log = parse(name)
        if not log:
            continue
        if step and not any(i['type'] == 'step' and i['name'] == step and i['status'] in ('FAIL', 'ERROR')
                            for i in log['items']):
            continue
        out.append(log)
    return out


def summary(logs):
    verdicts = Counter(l['verdict'] for l in logs)
    finished = sum(verdicts[v] for v in ('PASS', 'FAIL', 'ERROR'))
    # First-pass yield: the oldest finished run of every serial number.
    first = {}
    for l in sorted((l for l in logs if l['serial'] and l['verdict'] != 'STOPPED'), key=lambda l: l['started']):
        first.setdefault((l['script'], l['serial']), l['verdict'])
    boards = len(first)
    failures = Counter()
    for l in logs:
        for name in {i['name'] for i in l['items'] if i['type'] == 'step' and i['status'] in ('FAIL', 'ERROR')}:
            failures[name] += 1
    return {
        'runs': len(logs),
        'verdicts': {v: verdicts.get(v, 0) for v in VERDICTS},
        'yield': round(verdicts['PASS'] * 100 / finished, 1) if finished else None,
        'boards': boards,
        'fpy': round(sum(1 for v in first.values() if v == 'PASS') * 100 / boards, 1) if boards else None,
        'top_failures': [{'name': n, 'count': c} for n, c in failures.most_common(10)],
    }


def list_item(log):
    """Row for the log table (no step details)."""
    return {k: log[k] for k in ('name', 'script', 'serial', 'verdict', 'started', 'size', 'counts', 'first_fail')} | {
        'duration': log['footer'].get('duration'), 'host': log['header'].get('host', '')}


def step_values(logs, step):
    """Every occurrence of one step across logs, with measurement statistics when it has limits."""
    rows, values = [], []
    for log in logs:
        for i in log['items']:
            if i['type'] == 'step' and i['name'] == step:
                m = measurement(i['condition'])
                rows.append({'log': log['name'], 'started': log['started'], 'serial': log['serial'],
                             'status': i['status'], 'condition': i['condition'], 'units': i['units'],
                             'value': m[1] if m else None, 'lo': m[0] if m else None, 'hi': m[2] if m else None})
                if m:
                    values.append(m[1])
    st = Counter(r['status'] for r in rows)
    stats = {'n': len(rows), 'status': dict(st)}
    if values:
        stats.update(min=min(values), max=max(values), mean=round(statistics.fmean(values), 4),
                     stdev=round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
                     units=next((r['units'] for r in rows if r['units']), ''))
        lims = [(r['lo'], r['hi']) for r in rows if r['lo'] is not None]
        lo, hi = Counter(lims).most_common(1)[0][0]
        stats.update(lo=lo, hi=hi)
        if stats['stdev'] > 0:
            stats['cpk'] = round(min(hi - stats['mean'], stats['mean'] - lo) / (3 * stats['stdev']), 2)
    return {'step': step, 'stats': stats, 'rows': rows}


def to_csv(logs):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['started', 'script', 'serial', 'verdict', 'duration_s', 'pass', 'fail', 'error',
                'first_failure', 'first_failure_condition', 'host', 'log'])
    for l in logs:
        ff = l['first_fail'] or {}
        w.writerow([datetime.fromtimestamp(l['started']).strftime('%Y-%m-%d %H:%M:%S'), l['script'], l['serial'],
                    l['verdict'], l['footer'].get('duration', ''), l['counts']['PASS'], l['counts']['FAIL'],
                    l['counts']['ERROR'], ff.get('name', ''), ff.get('condition', ''),
                    l['header'].get('host', ''), l['name']])
    return buf.getvalue()
