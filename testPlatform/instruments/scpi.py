"""Common base for SCPI instruments (oscilloscope, bench multimeter, electronic load …).

A transport carries text lines (and IEEE 488.2 binary blocks) to the instrument:

    ScpiTcp("192.168.1.146", 5555)          # raw SCPI socket (LXI instruments: Rigol 5555, many others 5025)
    ScpiSerial("/dev/ttyUSB0", 115200)      # USB-serial / RS-232 instruments

and ``ScpiInstrument`` adds the usual commands on top. A driver subclasses it:

    class MyMeter(ScpiInstrument):
        def getVolt(self):
            return self.queryFloat("MEAS:VOLT:DC?")

    m = MyMeter(host="192.168.1.50", port=5025)     # or MyMeter(serial="/dev/ttyUSB0", baud=115200)
    m.idn()

The TCP connection stays open between commands and is re-opened once if it broke. Every exchange is serialised by
a lock, so a TestWatch check and the test steps can use the same instrument. Errors raise InstrumentError.
"""
import socket
import threading
import time
from typing import List, Optional


class InstrumentError(Exception):
    """The instrument cannot be reached, did not answer, or reported an error."""


# ── Transports ──────────────────────────────────────────────

class ScpiTcp:
    """Raw SCPI over a TCP socket; lines end with ``term`` (LF)."""

    def __init__(self, host: str, port: int = 5025, timeout: float = 3.0, term: str = "\n") -> None:
        self.host, self.port, self.timeout, self.term = host, port, timeout, term.encode()
        self._sock: Optional[socket.socket] = None
        self._buf = b""

    def __repr__(self) -> str:
        return f"tcp {self.host}:{self.port}"

    def open(self) -> None:
        if self._sock is None:
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            except OSError as e:
                raise InstrumentError(f"cannot connect to {self.host}:{self.port}: {e}")
            self._sock.settimeout(self.timeout)
            self._buf = b""

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def write(self, data: bytes) -> None:
        self.open()
        self._sock.sendall(data)

    def _recv(self) -> None:
        chunk = self._sock.recv(65536)
        if not chunk:
            raise InstrumentError(f"{self}: connection closed by the instrument")
        self._buf += chunk

    def readline(self) -> bytes:
        self.open()
        while self.term not in self._buf:
            self._recv()
        line, _, self._buf = self._buf.partition(self.term)
        return line

    def read_exact(self, n: int) -> bytes:
        self.open()
        while len(self._buf) < n:
            self._recv()
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def drain(self) -> None:
        """Throw away unread bytes (an answer to a timed-out query)."""
        self._buf = b""
        if self._sock is None:
            return
        self._sock.setblocking(False)
        try:
            while self._sock.recv(65536):
                pass
        except (BlockingIOError, OSError):
            pass
        finally:
            self._sock.settimeout(self.timeout)


class ScpiSerial:
    """SCPI over a serial port (pyserial); lines end with ``term``."""

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200, timeout: float = 3.0, term: str = "\n",
                 parity: str = "N", bytesize: int = 8, stopbits: int = 1) -> None:
        self.port, self.baud, self.timeout, self.term = port, baud, timeout, term.encode()
        self.parity, self.bytesize, self.stopbits = parity, bytesize, stopbits
        self._dev = None

    def __repr__(self) -> str:
        return f"serial {self.port} {self.baud}"

    def open(self) -> None:
        if self._dev is None:
            import serial                                     # pyserial (python3-serial)
            try:
                self._dev = serial.Serial(self.port, self.baud, bytesize=self.bytesize, parity=self.parity,
                                          stopbits=self.stopbits, timeout=self.timeout, write_timeout=self.timeout)
            except (serial.SerialException, OSError) as e:
                raise InstrumentError(f"cannot open {self.port}: {e}")

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None

    def write(self, data: bytes) -> None:
        self.open()
        self._dev.write(data)
        self._dev.flush()

    def readline(self) -> bytes:
        self.open()
        line = self._dev.read_until(self.term)
        if not line.endswith(self.term):
            raise socket.timeout("no line end")
        return line[:-len(self.term)]

    def read_exact(self, n: int) -> bytes:
        self.open()
        data = self._dev.read(n)
        if len(data) < n:
            raise socket.timeout("short read")
        return data

    def drain(self) -> None:
        if self._dev is not None:
            self._dev.reset_input_buffer()


# ── Instrument ─────────────────────────────────────────────

class ScpiInstrument:
    """SCPI instrument on a TCP socket (``host``) or a serial port (``serial``)."""

    DEFAULT_PORT = 5025
    DEFAULT_BAUD = 115200
    TERM = "\n"                       # line end of commands and answers
    WRITE_DELAY = 0.0                 # pause after a command without an answer (slow serial instruments)
    INVALID = 9.0e37                  # SCPI "no valid value" (9.9E37 overload / not measurable)

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, serial: Optional[str] = None,
                 baud: Optional[int] = None, timeout: float = 3.0) -> None:
        if bool(host) == bool(serial):
            raise ValueError("give host= (LAN) or serial= (USB / RS-232), not both")
        if host:
            self.link = ScpiTcp(host, port or self.DEFAULT_PORT, timeout, self.TERM)
        else:
            self.link = ScpiSerial(serial, baud or self.DEFAULT_BAUD, timeout, self.TERM)
        self.timeout = timeout
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.link!r})"

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection (it is opened again by the next command)."""
        with self._lock:
            self.link.close()

    # raw ------------------------------------------------------

    def _exchange(self, fn, cmd: str):
        """Run one exchange under the lock. A timeout is an error at once; a connection that broke while open
        (closed by the instrument, reset) is opened again and the exchange repeated once."""
        with self._lock:
            for attempt in (1, 2):
                try:
                    return fn()
                except socket.timeout:                      # (a subclass of OSError: handled first)
                    self.link.drain()
                    raise InstrumentError(f"{cmd}: no answer from {self.link!r} within {self.timeout} s")
                except InstrumentError as e:
                    self.link.close()
                    if str(e).startswith("cannot") or attempt == 2:
                        raise
                except OSError as e:
                    self.link.close()
                    if attempt == 2:
                        raise InstrumentError(f"{cmd}: {self.link!r}: {e}")

    def write(self, cmd: str) -> None:
        """Send a command that has no answer."""
        def go():
            self.link.write(cmd.encode("ascii") + self.TERM.encode())
            if self.WRITE_DELAY:
                time.sleep(self.WRITE_DELAY)
        self._exchange(go, cmd)

    def query(self, cmd: str) -> str:
        """Send a query, return the answer line (stripped)."""
        def go():
            self.link.write(cmd.encode("ascii") + self.TERM.encode())
            return self.link.readline().decode("ascii", errors="replace").strip()
        return self._exchange(go, cmd)

    def queryFloat(self, cmd: str) -> Optional[float]:
        """Query a number; None when the instrument reports "no valid value" (9.9E37) or an empty answer."""
        answer = self.query(cmd)
        try:
            v = float(answer.split(",")[0])
        except ValueError:
            if not answer or answer.strip("*-").upper() in ("", "NAN", "NONE", "OVLD", "OL"):
                return None
            raise InstrumentError(f"{cmd}: unexpected answer {answer!r}")
        return None if abs(v) >= self.INVALID else v

    def queryBlock(self, cmd: str) -> bytes:
        """Query binary data in an IEEE 488.2 definite length block (#<n><length><data>)."""
        def go():
            self.link.write(cmd.encode("ascii") + self.TERM.encode())
            head = self.link.read_exact(2)
            if head[:1] != b"#":
                rest = self.link.readline()
                raise InstrumentError(f"{cmd}: not a binary block: {(head + rest)[:60]!r}")
            digits = int(head[1:2])
            length = int(self.link.read_exact(digits)) if digits else 0
            data = self.link.read_exact(length)
            try:
                self.link.read_exact(len(self.TERM))         # the line end after the block
            except (socket.timeout, InstrumentError):
                pass
            return data
        return self._exchange(go, cmd)

    # common commands --------------------------------------------

    def idn(self) -> str:
        """*IDN? — manufacturer, model, serial number, firmware."""
        return self.query("*IDN?")

    def ping(self) -> bool:
        """True if the instrument answers *IDN?."""
        try:
            return bool(self.idn())
        except InstrumentError:
            return False

    def reset(self) -> None:
        """*RST — factory default settings."""
        self.write("*RST")

    def clearStatus(self) -> None:
        """*CLS — clear the status and the error queue."""
        self.write("*CLS")

    def waitDone(self, timeout: float = 10.0) -> None:
        """*OPC? — wait until the previous commands have finished."""
        old = self.link.timeout
        try:
            self.link.timeout = timeout
            if isinstance(self.link, ScpiTcp) and self.link._sock is not None:
                self.link._sock.settimeout(timeout)
            self.query("*OPC?")
        finally:
            self.link.timeout = old
            if isinstance(self.link, ScpiTcp) and self.link._sock is not None:
                self.link._sock.settimeout(old)

    def errors(self) -> List[str]:
        """Read the error queue (SYST:ERR?) until it is empty; [] = no errors."""
        out = []
        for _ in range(20):
            e = self.query(":SYSTem:ERRor?")
            if not e or e.startswith(("0,", "+0,")) or "no error" in e.lower():
                break
            out.append(e)
        return out
