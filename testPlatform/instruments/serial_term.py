"""Text terminal on a serial port: send a command, get the answer (UART consoles, AT modems, bootloaders …).

    from instruments.serial_term import SerialTerm

    uut = SerialTerm("/dev/ttyUSB0", 115200)                 # eol="\\r\\n", timeout=2.0
    ver = uut.cmd("VERSION?")                                  # text until the line goes quiet
    uut.cmd("AT", until="OK")                                  # until a word (or a regex: until=re.compile(…))
    uut.expect("login:", timeout=30)                           # wait for a boot prompt
    uut.close()

An answer ends at the first of: ``until`` seen, the ``prompt`` seen, ``idle`` seconds of silence after the last
byte, ``timeout``. The echo of the command and the prompt are cut off. TermError on timeout of expect() / until.
For binary protocols use instruments.uut_serial.UUTSerial.
"""
import re
import threading
import time
from typing import Optional, Pattern, Union

Match = Union[str, Pattern, None]


class TermError(Exception):
    """No answer / the expected text did not come in time / the port cannot be opened."""


def _find(text: str, what: Match):
    if what is None:
        return None
    if isinstance(what, str):
        i = text.find(what)
        return (i, i + len(what)) if i >= 0 else None
    m = what.search(text)
    return m.span() if m else None


class SerialTerm:
    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200, eol: str = "\r\n", timeout: float = 2.0,
                 idle: float = 0.2, prompt: Match = None, encoding: str = "utf-8", parity: str = "N",
                 bytesize: int = 8, stopbits: int = 1) -> None:
        self.port, self.baud, self.eol, self.timeout, self.idle = port, baud, eol, timeout, idle
        self.prompt, self.encoding = prompt, encoding
        self.parity, self.bytesize, self.stopbits = parity, bytesize, stopbits
        self._dev = None
        self._lock = threading.RLock()
        self.log = []                                    # [(dir, text)] of this session, newest last (max 500)

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:
        if self._dev is None:
            import serial
            try:
                self._dev = serial.Serial(self.port, self.baud, bytesize=self.bytesize, parity=self.parity,
                                          stopbits=self.stopbits, timeout=0.05, write_timeout=2)
            except (serial.SerialException, OSError) as e:
                raise TermError(f"cannot open {self.port}: {e}")

    def close(self) -> None:
        with self._lock:
            if self._dev is not None:
                try:
                    self._dev.close()
                finally:
                    self._dev = None

    def _note(self, d: str, text: str) -> None:
        self.log.append((d, text))
        del self.log[:-500]

    # ── Raw ─────────────────────────────────────────────────

    def write(self, text: str, eol: bool = True) -> None:
        """Send text (+ eol)."""
        with self._lock:
            self.open()
            data = (text + (self.eol if eol else "")).encode(self.encoding)
            self._dev.write(data)
            self._dev.flush()
            self._note("tx", text)

    def flush(self) -> str:
        """Read and drop what is waiting (old output); returns it."""
        with self._lock:
            self.open()
            data = self._dev.read(self._dev.in_waiting or 0)
            return data.decode(self.encoding, errors="replace")

    def read(self, until: Match = None, timeout: Optional[float] = None, idle: Optional[float] = None) -> str:
        """Collect text until ``until`` / prompt / ``idle`` s of silence / ``timeout`` (see module doc)."""
        timeout = self.timeout if timeout is None else timeout
        idle = self.idle if idle is None else idle
        with self._lock:
            self.open()
            buf, start, last = "", time.time(), None
            while True:
                chunk = self._dev.read(self._dev.in_waiting or 1)
                now = time.time()
                if chunk:
                    buf += chunk.decode(self.encoding, errors="replace")
                    last = now
                    if _find(buf, until) or (until is None and _find(buf, self.prompt)):
                        break
                elif until is None and last is not None and idle and now - last >= idle:
                    break
                if now - start >= timeout:
                    if until is not None:
                        self._note("rx", buf)
                        raise TermError(f"{until!r} not received within {timeout} s (got {buf[-200:]!r})")
                    break
            self._note("rx", buf)
            return buf

    # ── Command / answer ────────────────────────────────────

    def cmd(self, command: str, until: Match = None, timeout: Optional[float] = None,
            idle: Optional[float] = None) -> str:
        """Send a command, return its answer without the echo, the prompt and the outer whitespace."""
        with self._lock:
            self.flush()
            self.write(command)
            out = self.read(until=until, timeout=timeout, idle=idle)
        text = out.replace("\r\n", "\n").replace("\r", "\n")
        if text.lstrip().startswith(command):                       # echo of a console
            text = text.lstrip()[len(command):]
        span = _find(text, self.prompt)
        if span:
            text = text[:span[0]]
        return text.strip()

    def expect(self, what: Match, timeout: Optional[float] = None) -> str:
        """Wait for a text / regex (e.g. a boot prompt); returns everything received up to it."""
        if what is None:
            raise ValueError("expect what?")
        return self.read(until=what, timeout=timeout)

    def lines(self, command: str, **kw) -> list:
        """cmd() split into non-empty lines."""
        return [ln for ln in self.cmd(command, **kw).splitlines() if ln.strip()]

    def value(self, command: str, pattern: str = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", **kw) -> Optional[float]:
        """First number in the answer (or the first group of ``pattern``); None if there is none."""
        m = re.search(pattern, self.cmd(command, **kw))
        if not m:
            return None
        return float(m.group(1) if m.groups() else m.group(0))


SERIAL_TERM = SerialTerm
