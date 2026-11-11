"""Files for test scripts: parameters by key (calibration values, counters, settings of a station) and plain text.

    from instruments.param_file import ParamFile, data_path

    cal = ParamFile(data_path("calibration.ini"))             # testPlatform/data/calibration.ini
    cal.create({"offset": 0.0, "gain": 1.0})                   # only if it does not exist yet
    gain = cal.get("gain", 1.0)                                 # 1.0 (float — the type is read back)
    cal.set("offset", 0.012)                                    # written to disk at once (atomic)
    n = cal.increment("boards_tested")                          # counters

Format by extension: ``.json`` → JSON object; anything else → ``key = value`` lines (comments ``#`` / ``;`` and
blank lines are kept, ``[sections]`` are allowed but ignored). Values come back typed: int, float, bool
(true/false/yes/no/on/off), None (empty), else str. Every write goes through a temporary file + rename, so a
power loss never leaves a half-written file.

Relative paths are relative to testPlatform/, not to the current directory (the runner and SSH start scripts
from different places); data_path() puts files into testPlatform/data/.
"""
import json
import os
import re
import tempfile
import threading
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # testPlatform/
DATA_DIR = os.path.join(BASE, "data")
_LINE = re.compile(r"^\s*([^=#;\[\s][^=]*?)\s*=\s*(.*?)\s*$")


class ParamError(Exception):
    """The file cannot be read / written, or its content is not understood."""


def data_path(name: str) -> str:
    """Absolute path of a file in testPlatform/data/ (the folder is created)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


def _abs(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(BASE, path)


def _atomic_write(path: str, text: str) -> None:
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def parse_value(text: str) -> Any:
    """'12' → 12, '1.5' → 1.5, 'true' → True, '' → None, quoted / other text → str."""
    t = text.strip()
    if t == "":
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    low = t.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    for conv in (int, float):
        try:
            return conv(t)
        except ValueError:
            pass
    return t


def format_value(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s != s.strip() or "\n" in s or parse_value(s) != s:              # keep "007", " x", "true" as text
        return json.dumps(s)
    return s


class ParamFile:
    def __init__(self, path: str) -> None:
        self.path = _abs(path)
        self.json = self.path.lower().endswith(".json")
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"ParamFile({self.path!r})"

    # ── Read ────────────────────────────────────────────────

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def _lines(self) -> List[str]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return f.read().splitlines()
        except FileNotFoundError:
            return []
        except OSError as e:
            raise ParamError(f"{self.path}: {e}")

    def all(self) -> Dict[str, Any]:
        """Every key with its typed value ({} if the file does not exist)."""
        if self.json:
            if not self.exists():
                return {}
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError) as e:
                raise ParamError(f"{self.path}: {e}")
            if not isinstance(data, dict):
                raise ParamError(f"{self.path}: not a JSON object")
            return data
        out = {}
        for ln in self._lines():
            m = _LINE.match(ln)
            if m:
                out[m.group(1)] = parse_value(m.group(2))
        return out

    def get(self, key: str, default: Any = None) -> Any:
        """Value of a key, or ``default`` when the key / the file is missing."""
        return self.all().get(key, default)

    def has(self, key: str) -> bool:
        return key in self.all()

    def keys(self) -> List[str]:
        return list(self.all())

    # ── Write ───────────────────────────────────────────────

    def create(self, defaults: Optional[Dict[str, Any]] = None, overwrite: bool = False) -> bool:
        """Create the file with ``defaults`` if it does not exist (or ``overwrite``); True if it was written.
        Missing default keys are NOT added to an existing file — use setMany() for that."""
        with self._lock:
            if self.exists() and not overwrite:
                return False
            self._write(dict(defaults or {}), fresh=True)
            return True

    def set(self, key: str, value: Any) -> None:
        """Write one key (added at the end if new; comments and order of the other lines kept)."""
        self.setMany({key: value})

    def setMany(self, values: Dict[str, Any]) -> None:
        """Write several keys at once (one disk write)."""
        for k in values:
            if not isinstance(k, str) or not k.strip() or any(c in k for c in "=\n#;[") or k != k.strip():
                raise ValueError(f"bad key {k!r}")
        with self._lock:
            self._write(values)

    def delete(self, key: str) -> bool:
        """Remove a key; True if it was there."""
        with self._lock:
            if self.json:
                data = self.all()
                if key not in data:
                    return False
                data.pop(key)
                _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                return True
            lines = self._lines()
            keep = [ln for ln in lines if not ((_LINE.match(ln) or [None, None])[1] == key)]
            if len(keep) == len(lines):
                return False
            _atomic_write(self.path, "\n".join(keep) + "\n")
            return True

    def increment(self, key: str, step: float = 1) -> float:
        """Add ``step`` to a numeric key (missing = 0) and return the new value."""
        with self._lock:
            v = self.all().get(key) or 0
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ParamError(f"{key}: not a number ({v!r})")
            v = v + step
            self._write({key: v})
            return v

    def _write(self, values: Dict[str, Any], fresh: bool = False) -> None:
        if self.json:
            data = {} if fresh else self.all()
            data.update(values)
            _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            return
        lines = [] if fresh else self._lines()
        todo = dict(values)
        for i, ln in enumerate(lines):
            m = _LINE.match(ln)
            if m and m.group(1) in todo:
                lines[i] = f"{m.group(1)} = {format_value(todo.pop(m.group(1)))}"
        lines += [f"{k} = {format_value(v)}" for k, v in todo.items()]
        _atomic_write(self.path, "\n".join(lines) + "\n")

    # ── Plain text helpers ──────────────────────────────────

    def readText(self) -> str:
        """The whole file as text ('' if it does not exist)."""
        return "\n".join(self._lines())

    def writeText(self, text: str) -> None:
        """Replace the file with a text."""
        with self._lock:
            _atomic_write(self.path, text)

    def appendLine(self, line: str) -> None:
        """Add one line at the end (a simple log / CSV)."""
        with self._lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line.rstrip("\n") + "\n")
