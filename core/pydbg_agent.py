"""Debugger agent that runs *inside* the debugged Python process (started by core/pyrun.py).

Launched as ``python3 -u -c "…; import pydbg_agent; pydbg_agent.main()" <script> [args…]`` with
``SMMS_DBG_FDS=<cmd_read_fd>,<event_write_fd>``. The script's stdin/stdout/stderr stay on the terminal (a pty),
so its console behaviour is unchanged; the debugger talks to the panel over the two pipes, one JSON object per
line.

Commands (panel → agent):  {"cmd": "continue"|"next"|"step"|"return"|"stop"|"pause"}
                           {"cmd": "breaks", "breaks": {"/abs/file.py": [lines]}}
                           {"cmd": "eval", "id": n, "expr": "...", "frame": i, "hover": bool}
                           {"cmd": "vars", "id": n, "expr": "..." | null, "frame": i}
                           {"cmd": "frame", "frame": i}
Events (agent → panel):    {"ev": "paused", "reason", "file", "line", "func", "stack": [...], "frame": i, "vars": [...]}
                           {"ev": "running"} · {"ev": "reply", "id", ...} · {"ev": "exception", "text"} · {"ev": "done"}

Only standard library modules are used here (the debugged program may run without the panel's packages).
"""
import ast
import bdb
import json
import linecache
import os
import queue
import reprlib
import sys
import threading
import traceback

MAX_CHILDREN = 200
_repr = reprlib.Repr()
_repr.maxstring = 300
_repr.maxother = 300
_repr.maxlist = _repr.maxtuple = _repr.maxset = _repr.maxdict = 30
_repr.maxlevel = 3

HIDDEN_TYPES = ('module', 'function', 'builtin_function_or_method', 'type', 'method')


def _safe_repr(value):
    try:
        return _repr.repr(value)
    except Exception as e:     # a broken __repr__ must not break the debugger
        return f'<repr failed: {type(e).__name__}: {e}>'


def _expandable(value):
    if isinstance(value, (str, bytes, bytearray, int, float, complex, bool, type(None))):
        return False
    if isinstance(value, (dict, list, tuple, set, frozenset)):
        return len(value) > 0
    return bool(getattr(value, '__dict__', None)) or hasattr(value, '__slots__')


def describe(name, value, expr):
    t = type(value)
    size = None
    try:
        if isinstance(value, (dict, list, tuple, set, frozenset, str, bytes, bytearray)):
            size = len(value)
    except Exception:
        pass
    return {'name': name, 'type': t.__name__, 'value': _safe_repr(value), 'expr': expr,
            'more': _expandable(value), 'len': size}


def children(value, expr):
    out = []
    if isinstance(value, dict):
        for i, (k, v) in enumerate(value.items()):
            if i >= MAX_CHILDREN:
                break
            out.append(describe(_safe_repr(k), v, f'{expr}[{k!r}]' if _literal(k) else None))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value[:MAX_CHILDREN]):
            out.append(describe(f'[{i}]', v, f'{expr}[{i}]'))
    elif isinstance(value, (set, frozenset)):
        for i, v in enumerate(list(value)[:MAX_CHILDREN]):
            out.append(describe(f'{{{i}}}', v, None))
    else:
        names = list(getattr(value, '__dict__', {}) or {})
        for slot in getattr(type(value), '__slots__', ()) or ():
            if isinstance(slot, str) and slot not in names and hasattr(value, slot):
                names.append(slot)
        for n in sorted(names)[:MAX_CHILDREN]:
            try:
                out.append(describe(n, getattr(value, n), f'{expr}.{n}'))
            except Exception as e:
                out.append({'name': n, 'type': 'error', 'value': str(e), 'expr': None, 'more': False, 'len': None})
    return out


def _literal(k):
    try:
        return ast.literal_eval(repr(k)) == k
    except Exception:
        return False


def hover_safe(expr):
    """Only names, attributes and constant subscripts — hovering must never call code by accident."""
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.Name, ast.Attribute, ast.Subscript, ast.Constant, ast.Load,
                                 ast.UnaryOp, ast.USub)):
            return False
    return True


def scope_vars(frame):
    """Visible variables of a frame: locals (+ globals for function frames), without modules/functions/classes."""
    items = []
    loc = frame.f_locals
    for k, v in loc.items():
        if k.startswith('__') and k.endswith('__'):
            continue
        if type(v).__name__ in HIDDEN_TYPES and frame.f_code.co_name == '<module>':
            continue
        items.append(describe(k, v, k))
    return items


class Agent(bdb.Bdb):
    def __init__(self, cmd_fd, ev_fd, main_file, roots):
        super().__init__()
        self._cmd = os.fdopen(cmd_fd, 'r', encoding='utf-8', errors='replace')
        self._ev = os.fdopen(ev_fd, 'w', encoding='utf-8')
        self._ev_lock = threading.Lock()
        self.queue = queue.Queue()
        self.main_file = self.canonic(main_file)
        self.roots = [os.path.realpath(r) + os.sep for r in roots if r]
        self.waiting_main = True
        self.stop_on_entry = False
        self.frames = []          # stack of the current pause: [(frame, lineno)]
        self.cur = 0
        self.main_thread = threading.get_ident()
        self.quitting_requested = False
        self._lines = {}          # traced frame -> (current line, previous line)
        self._line_frame = None   # frame of the line event we are paused in (only it can jump)
        threading.Thread(target=self._reader, name='smms-dbg-reader', daemon=True).start()

    # ── channel ──
    def send(self, **ev):
        line = json.dumps(ev, default=str)
        with self._ev_lock:
            try:
                self._ev.write(line + '\n')
                self._ev.flush()
            except (BrokenPipeError, ValueError):
                pass

    def _reader(self):
        for line in self._cmd:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            c = msg.get('cmd')
            if c == 'breaks':
                self._set_breaks(msg.get('breaks') or {})
                self.send(ev='reply', id=msg.get('id'), ok=True)
            elif c == 'pause':
                self._pause()
            elif c == 'stop':
                self.quitting_requested = True
                if not self.frames:
                    self._pause()
                self.queue.put(msg)
            else:
                self.queue.put(msg)
        # the panel went away: let the program finish without stopping
        self.queue.put({'cmd': 'detach'})

    def _set_breaks(self, breaks):
        for f in list(self.breaks):
            self.clear_all_file_breaks(f)
        for f, lines in breaks.items():
            f = self.canonic(f)
            for ln in lines:
                try:
                    ln = int(ln)
                except (TypeError, ValueError):
                    continue
                if linecache.getline(f, ln):
                    self.set_break(f, ln)

    def _pause(self):
        """Stop at the next line of user code (also in frames that are not traced yet)."""
        self._set_stopinfo(None, None)
        frame = sys._current_frames().get(self.main_thread)
        while frame is not None:
            if frame.f_trace is None and self._mine(frame):
                frame.f_trace = self.trace_dispatch
            frame = frame.f_back

    # ── filtering: "just my code" ──
    def _mine(self, frame):
        fn = self.canonic(frame.f_code.co_filename)
        if fn.startswith('<'):
            return False
        if fn == self.main_file:
            return True
        if any(fn.startswith(r) for r in self.roots):
            return not ('site-packages' in fn or 'dist-packages' in fn)
        return False

    def stop_here(self, frame):
        if not self._mine(frame):
            return False
        return super().stop_here(frame)

    def dispatch_line(self, frame):
        # remember the previous line of every traced frame (for "run the previous line again")
        cur = self._lines.get(frame)
        if not cur or cur[0] != frame.f_lineno:
            self._lines[frame] = (frame.f_lineno, cur[0] if cur else None)
        return super().dispatch_line(frame)

    def dispatch_return(self, frame, arg):
        self._lines.pop(frame, None)
        return super().dispatch_return(frame, arg)

    def set_continue(self):
        # Keep tracing (bdb drops the trace function when there are no breakpoints): breakpoints may be added
        # and Pause pressed while the program runs.
        self._set_stopinfo(self.botframe, None, -1)

    # ── bdb hooks ──
    def user_call(self, frame, argument_list):
        pass      # step into stops at the first line of the function (user_line), not at the call event

    def user_line(self, frame):
        if self.waiting_main:
            if self.canonic(frame.f_code.co_filename) != self.main_file or frame.f_lineno <= 0:
                return
            self.waiting_main = False
            if not self.stop_on_entry and not self.break_here(frame):
                self.set_continue()
                return
            self._line_frame = frame
            self.interaction(frame, 'entry' if self.stop_on_entry else 'breakpoint')
            return
        if self.quitting_requested:
            raise bdb.BdbQuit
        self._line_frame = frame
        self.interaction(frame, 'breakpoint' if self.break_here(frame) else 'step')

    def user_return(self, frame, return_value):
        # Leaving a function while stepping (next over its last line / step out): stop at the caller's next line.
        if self._mine(frame) and frame.f_code.co_name != '<module>':
            self.set_step()

    def user_exception(self, frame, exc_info):
        pass      # caught exceptions do not stop; uncaught ones end in post_mortem()

    # ── pause loop ──
    def _stack(self, frame, tb=None):
        stack, _ = self.get_stack(frame, tb)
        mine = [(f, ln) for f, ln in stack if self._mine(f)]
        return mine or stack[-1:]

    def _frame_info(self):
        return [{'file': self.canonic(f.f_code.co_filename), 'line': ln, 'func': f.f_code.co_name}
                for f, ln in self.frames]

    def _paused_event(self, reason, extra=None):
        f, ln = self.frames[self.cur]
        ev = {'ev': 'paused', 'reason': reason, 'file': self.canonic(f.f_code.co_filename), 'line': ln,
              'func': f.f_code.co_name, 'stack': self._frame_info(), 'frame': self.cur, 'vars': self._vars(f)}
        if extra:
            ev.update(extra)
        self.send(**ev)

    @staticmethod
    def _vars(frame):
        try:
            return scope_vars(frame)
        except Exception as e:
            return [{'name': '<error>', 'type': 'error', 'value': str(e), 'expr': None, 'more': False, 'len': None}]

    def interaction(self, frame, reason, tb=None, extra=None):
        self.frames = self._stack(frame, tb)
        self.cur = len(self.frames) - 1
        self._paused_event(reason, extra)
        try:
            while True:
                msg = self.queue.get()
                c = msg.get('cmd')
                f = self.frames[self.cur][0]
                if c == 'continue':
                    self.set_continue()
                elif c == 'next':
                    self.set_next(f)
                elif c == 'step':
                    self.set_step()
                elif c == 'return':
                    self.set_return(f)
                elif c in ('stop', 'detach'):
                    if c == 'detach':
                        self.clear_all_breaks()
                        self.set_continue()
                        sys.settrace(None)
                        break
                    self.set_quit()
                elif c == 'frame':
                    i = int(msg.get('frame', self.cur))
                    if 0 <= i < len(self.frames):
                        self.cur = i
                    self._paused_event(reason, extra)
                    continue
                elif c in ('eval', 'vars'):
                    self._answer(msg)
                    continue
                elif c == 'jump':
                    self._jump(msg, reason, extra)
                    continue
                else:
                    continue
                break
        finally:
            self.frames = []
            self._line_frame = None
        if not self.quitting:
            self.send(ev='running')

    def _jump(self, msg, reason, extra):
        """Set the next line of the paused frame (like pdb "jump"): line = number, or None = the previous
        executed line. Nothing is undone — variables keep their values."""
        rid = msg.get('id')
        f = self.frames[-1][0] if self.frames else None
        if f is None or f is not self._line_frame or self.cur != len(self.frames) - 1:
            self.send(ev='reply', id=rid, error='Only the current line of the innermost frame can be moved')
            return
        line = msg.get('line')
        if line is None:
            cur, prev = self._lines.get(f, (f.f_lineno, None))
            line = prev if prev and prev != f.f_lineno else None
            if line is None:                       # not tracked (paused by Pause): the line above
                n = f.f_lineno - 1
                while n > f.f_code.co_firstlineno and not linecache.getline(f.f_code.co_filename, n).strip():
                    n -= 1
                line = n
        try:
            line = int(line)
            f.f_lineno = line
        except (ValueError, TypeError) as e:
            self.send(ev='reply', id=rid, error=f'Cannot jump to line {line}: {e}')
            return
        self._lines[f] = (line, self._lines.get(f, (None, None))[0])
        self.frames[-1] = (f, line)
        self.send(ev='reply', id=rid, ok=True, line=line)
        self._paused_event(reason, extra)

    def _answer(self, msg):
        rid, expr = msg.get('id'), msg.get('expr')
        i = msg.get('frame', self.cur)
        if not isinstance(i, int) or not 0 <= i < len(self.frames):
            i = self.cur
        f = self.frames[i][0]
        try:
            if msg.get('cmd') == 'vars' and not expr:
                self.send(ev='reply', id=rid, vars=self._vars(f))
                return
            if msg.get('hover') and not hover_safe(expr):
                self.send(ev='reply', id=rid, error='not a plain name')
                return
            value = eval(expr, f.f_globals, f.f_locals)   # noqa: S307 — the user's own debug session
            if msg.get('cmd') == 'vars':
                self.send(ev='reply', id=rid, vars=children(value, expr))
            else:
                self.send(ev='reply', id=rid, result=describe(expr, value, expr))
        except Exception as e:
            self.send(ev='reply', id=rid, error=f'{type(e).__name__}: {e}')

    def post_mortem(self, tb):
        exc = sys.exc_info()[1]
        text = ''.join(traceback.format_exception(type(exc), exc, tb))
        self.send(ev='exception', text=text)
        self.reset()
        self.interaction(None, 'exception', tb=tb, extra={'exception': f'{type(exc).__name__}: {exc}'})


def main():
    fds = os.environ.pop('SMMS_DBG_FDS', '')
    roots = [r for r in os.environ.pop('SMMS_DBG_ROOTS', '').split(os.pathsep) if r]
    stop_on_entry = os.environ.pop('SMMS_DBG_ENTRY', '') == '1'
    breaks = json.loads(os.environ.pop('SMMS_DBG_BREAKS', '{}') or '{}')
    cmd_fd, ev_fd = (int(x) for x in fds.split(','))
    if len(sys.argv) < 2:
        print('usage: pydbg_agent <script> [args]', file=sys.stderr)
        sys.exit(2)
    script = os.path.realpath(sys.argv[1])
    sys.argv = [script] + sys.argv[2:]
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.realpath(p or '.') != here]   # do not shadow the script's imports
    sys.path.insert(0, os.path.dirname(script))
    os.chdir(os.path.dirname(script))

    agent = Agent(cmd_fd, ev_fd, script, roots + [os.path.dirname(script)])
    agent.stop_on_entry = stop_on_entry
    agent._set_breaks(breaks)

    import __main__
    __main__.__dict__.clear()
    __main__.__dict__.update({'__name__': '__main__', '__file__': script, '__builtins__': __builtins__})
    with open(script, 'rb') as fh:
        code = compile(fh.read(), script, 'exec')
    status = 0
    try:
        agent.run(code, __main__.__dict__)
    except bdb.BdbQuit:
        status = 130
    except SystemExit as e:
        status = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if e.code not in (None, 0) and not isinstance(e.code, int):
            print(e.code, file=sys.stderr)
    except BaseException:
        status = 1
        _, _, tb = sys.exc_info()
        traceback.print_exc()
        sys.stderr.flush()
        if not agent.quitting_requested:          # Stop pressed: no post-mortem pause
            try:
                agent.post_mortem(tb)
            except bdb.BdbQuit:
                pass
    finally:
        sys.settrace(None)
        if agent.quitting_requested and status == 0:
            status = 130                          # stopped from the editor (bdb.run swallows BdbQuit)
        sys.stdout.flush()
        agent.send(ev='done', status=status)
    os._exit(status if isinstance(status, int) else 1)
