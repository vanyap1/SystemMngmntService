"""Modbus master, low level (like the HW Utils Modbus monitor): raw function codes, registers / bits as numbers.

    from instruments.modbus import ModbusRTU, ModbusTCP

    mb = ModbusRTU("/dev/ttyUSB0", 115200, unit=1)              # RS-485; parity="N", bytesize=8, stopbits=1
    regs = mb.readHolding(0, 12)                                # fn 03 → [int 0..65535]
    mb.writeRegister(20, 1)                                     # fn 06
    print(mb.last)                                              # {"tx": "01 03 …", "rx": "01 03 18 …", "ms": 12.3}
    mb.close()                                                  # in finalize()

    mb = ModbusTCP("192.168.1.50")                              # port=502; also ModbusUDP, ModbusRTUoverTCP / UDP

Functions: 01 readCoils, 02 readDiscrete, 03 readHolding, 04 readInput, 05 writeCoil, 06 writeRegister,
15 writeCoils, 16 writeRegisters, any other with request(fn, data). Every call takes ``unit=`` to talk to another
device on the same line. Values travel raw; to_s16 / to_u32 / to_s32 / to_float32 / to_ascii (+ word swap) turn
registers into numbers and text, like the monitor's format column.

Errors: ModbusException(code) when the device answers with an exception (02 = illegal data address …),
ModbusError on timeout, CRC error or when the port / host cannot be opened. ``retries`` repeats a request after a
timeout or a CRC error (noisy RS-485), never after an exception answer.

The serial port is opened with the first request and stays open (exclusive) until close() — a test owns its bus.
Sockets reconnect by themselves after the peer closed them. No core/ imports, only pyserial for RTU.
"""
import socket
import struct
import threading
import time
from typing import List, Optional, Sequence

EXCEPTIONS = {1: "illegal function", 2: "illegal data address", 3: "illegal data value", 4: "server device failure",
              5: "acknowledge", 6: "server device busy", 8: "memory parity error", 10: "gateway path unavailable",
              11: "gateway target failed to respond"}
READ_LIMIT = {1: 2000, 2: 2000, 3: 125, 4: 125}
WRITE_LIMIT = {15: 1968, 16: 123}


class ModbusError(Exception):
    """No / bad answer (timeout, CRC, wrong unit) or the port cannot be opened."""


class ModbusException(ModbusError):
    """The device answered with a Modbus exception; ``code`` = exception code."""

    def __init__(self, fn: int, code: int) -> None:
        self.fn, self.code = fn, code
        super().__init__(f"function {fn}: exception {code} ({EXCEPTIONS.get(code, 'unknown')})")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _hex(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ── Register formats ────────────────────────────────────────

def _pairs(regs: Sequence[int], swap: bool) -> List[int]:
    out = []
    for i in range(0, len(regs) - 1, 2):
        hi, lo = (regs[i + 1], regs[i]) if swap else (regs[i], regs[i + 1])
        out.append((hi << 16) | lo)
    return out


def to_s16(regs: Sequence[int]) -> List[int]:
    """Registers as signed 16-bit numbers."""
    return [r - 0x10000 if r & 0x8000 else r for r in regs]


def to_u32(regs: Sequence[int], swap: bool = False) -> List[int]:
    """Register pairs as unsigned 32-bit (high word first; ``swap`` = low word first)."""
    return _pairs(regs, swap)


def to_s32(regs: Sequence[int], swap: bool = False) -> List[int]:
    return [v - 0x100000000 if v & 0x80000000 else v for v in _pairs(regs, swap)]


def to_float32(regs: Sequence[int], swap: bool = False) -> List[float]:
    """Register pairs as IEEE-754 float32."""
    return [struct.unpack(">f", struct.pack(">I", v))[0] for v in _pairs(regs, swap)]


def to_ascii(regs: Sequence[int], swap_bytes: bool = False) -> str:
    """Registers as text, 2 characters each (high byte first), NULs removed."""
    raw = b"".join(struct.pack("<H" if swap_bytes else ">H", r) for r in regs)
    return raw.replace(b"\x00", b"").decode("latin-1")


def from_float32(value: float, swap: bool = False) -> List[int]:
    """A float as two registers (for writeRegisters)."""
    hi, lo = struct.unpack(">HH", struct.pack(">f", value))
    return [lo, hi] if swap else [hi, lo]


def from_u32(value: int, swap: bool = False) -> List[int]:
    v = int(value) & 0xFFFFFFFF
    hi, lo = v >> 16, v & 0xFFFF
    return [lo, hi] if swap else [hi, lo]


# ── Master ──────────────────────────────────────────────────

class ModbusMaster:
    """Base of the transports; use ModbusRTU, ModbusTCP, ModbusUDP, ModbusRTUoverTCP, ModbusRTUoverUDP."""
    RTU = True              # RTU framing (unit + PDU + CRC) or MBAP (TCP / UDP)
    STREAM = True           # serial / TCP stream or UDP datagrams

    def __init__(self, unit: int = 1, timeout: float = 0.5, retries: int = 0) -> None:
        self.unit, self.timeout, self.retries = int(unit), float(timeout), int(retries)
        self.last = {}                                  # tx / rx hex and time of the last request
        self._dev = None
        self._tid = 0
        self._lock = threading.RLock()
        self._next = 0.0                                # earliest time of the next RTU frame (silent interval)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # transport hooks -------------------------------------

    def _open(self):
        raise NotImplementedError

    def _write(self, data: bytes) -> None:
        self._dev.sendall(data)

    def _read(self, n: int, deadline: float) -> bytes:
        """Exactly n bytes of a stream before the deadline (fewer = timeout)."""
        buf = b""
        while len(buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            self._dev.settimeout(left)
            try:
                chunk = self._dev.recv(n - len(buf))
            except socket.timeout:
                break
            if not chunk:
                self.close()
                raise ModbusError("connection closed by the device")
            buf += chunk
        return buf

    def _drain(self) -> bool:
        """Drop late bytes of a timed-out request before the next one; False if the peer closed the socket."""
        self._dev.setblocking(False)
        try:
            while True:
                if not self._dev.recv(4096):
                    return False
        except (BlockingIOError, InterruptedError):
            return True
        except OSError:
            return False
        finally:
            self._dev.settimeout(self.timeout)

    def _gap(self) -> float:
        return 0.0

    # core ------------------------------------------------

    def close(self) -> None:
        """Close the port / socket (the next request opens it again)."""
        with self._lock:
            if self._dev is not None:
                try:
                    self._dev.close()
                except OSError:
                    pass
                self._dev = None

    def request(self, fn: int, data: bytes = b"", unit: Optional[int] = None) -> Optional[bytes]:
        """Send function ``fn`` with raw ``data``; returns the answer PDU without the function byte (None for a
        broadcast, unit 0). Retries after a timeout / CRC error as set by ``retries``."""
        unit = self.unit if unit is None else int(unit)
        if not 0 <= unit <= 255 or not 1 <= fn <= 127:
            raise ValueError("unit 0..255, function 1..127")
        last = None
        for _ in range(self.retries + 1):
            try:
                return self._transact(unit, bytes([fn]) + bytes(data))
            except ModbusException:
                raise
            except ModbusError as e:
                last = e
        raise last

    def _transact(self, unit: int, pdu: bytes) -> Optional[bytes]:
        fn = pdu[0]
        with self._lock:
            if self._dev is not None and self.STREAM and not self._drain():
                self.close()                                # peer closed the connection: open a new one
            if self._dev is None:
                self._dev = self._open()
            wait = self._next - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            t0 = time.monotonic()
            deadline = t0 + self.timeout
            if self.RTU:
                frame = bytes([unit]) + pdu
                frame += struct.pack("<H", crc16(frame))
            else:
                self._tid = (self._tid + 1) & 0xFFFF
                frame = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, unit) + pdu
            self.last = {"tx": _hex(frame), "rx": "", "ms": 0.0}
            try:
                self._write(frame)
                if unit == 0 and self.RTU:
                    self._next = time.monotonic() + max(self._gap(), 0.05)    # broadcast: devices need time
                    return None
                rx = self._receive(fn, deadline)
            except OSError as e:
                self.close()
                raise ModbusError(f"{self!r}: {e}")
            finally:
                self._next = max(self._next, time.monotonic() + self._gap())
                self.last["ms"] = round((time.monotonic() - t0) * 1000, 1)
            self.last["rx"] = _hex(rx)
        if self.RTU:
            if len(rx) < 4 or crc16(rx[:-2]) != struct.unpack("<H", rx[-2:])[0]:
                raise ModbusError(f"CRC error in the answer ({_hex(rx)})")
            if rx[0] != unit:
                raise ModbusError(f"answer from unit {rx[0]} instead of {unit}")
            body = rx[1:-2]
        else:
            if len(rx) < 9:
                raise ModbusError(f"short answer ({_hex(rx)})")
            tid, proto = struct.unpack(">HH", rx[:4])
            if tid != self._tid or proto != 0:
                raise ModbusError("answer to another request (transaction id)")
            body = rx[7:]
        if body[0] == fn | 0x80:
            raise ModbusException(fn, body[1] if len(body) > 1 else 0)
        if body[0] != fn:
            raise ModbusError(f"answer with function {body[0]} instead of {fn}")
        return body[1:]

    def _receive(self, fn: int, deadline: float) -> bytes:
        if not self.STREAM:
            self._dev.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                return self._dev.recv(512)
            except socket.timeout:
                raise ModbusError("timeout — no answer")
        if self.RTU:
            rx = self._need(2, deadline, b"")
            if rx[1] & 0x80:
                rx += self._need(3, deadline, rx)
            elif rx[1] in (1, 2, 3, 4):
                rx += self._need(1, deadline, rx)
                rx += self._need(rx[2] + 2, deadline, rx)
            elif rx[1] in (5, 6, 15, 16):
                rx += self._need(6, deadline, rx)
            else:                                           # unknown length: read until the line is quiet
                rx += self._quiet(deadline)
            return rx
        rx = self._need(7, deadline, b"")
        return rx + self._need(struct.unpack(">H", rx[4:6])[0] - 1, deadline, rx)

    def _need(self, n: int, deadline: float, got: bytes) -> bytes:
        part = self._read(n, deadline)
        if len(part) < n:
            self.last["rx"] = _hex(got + part)
            raise ModbusError("timeout — no answer" if not got + part
                              else f"timeout — incomplete answer ({_hex(got + part)})")
        return part

    def _quiet(self, deadline: float) -> bytes:
        buf = b""
        while time.monotonic() < deadline:
            chunk = self._read(1, min(deadline, time.monotonic() + 0.05))
            if not chunk:
                break
            buf += chunk
        return buf

    # function codes --------------------------------------

    def _read_bits(self, fn: int, addr: int, count: int, unit: Optional[int]) -> List[int]:
        self._check(addr, count, READ_LIMIT[fn])
        body = self.request(fn, struct.pack(">HH", addr, count), unit)
        data = body[1:1 + body[0]]
        if len(data) * 8 < count:
            raise ModbusError(f"{len(data) * 8} bits instead of {count}")
        return [(data[i // 8] >> (i % 8)) & 1 for i in range(count)]

    def _read_regs(self, fn: int, addr: int, count: int, unit: Optional[int]) -> List[int]:
        self._check(addr, count, READ_LIMIT[fn])
        body = self.request(fn, struct.pack(">HH", addr, count), unit)
        n = body[0] // 2
        if n != count:
            raise ModbusError(f"{n} register(s) instead of {count}")
        return list(struct.unpack(f">{n}H", body[1:1 + 2 * n]))

    @staticmethod
    def _check(addr: int, count: int, limit: int) -> None:
        if not 0 <= addr <= 0xFFFF or not 1 <= count <= limit or addr + count > 0x10000:
            raise ValueError(f"address 0..65535, count 1..{limit}")

    def readCoils(self, addr: int, count: int = 1, unit: Optional[int] = None) -> List[int]:
        """Function 01 → [0/1]."""
        return self._read_bits(1, addr, count, unit)

    def readDiscrete(self, addr: int, count: int = 1, unit: Optional[int] = None) -> List[int]:
        """Function 02 (discrete inputs) → [0/1]."""
        return self._read_bits(2, addr, count, unit)

    def readHolding(self, addr: int, count: int = 1, unit: Optional[int] = None) -> List[int]:
        """Function 03 (holding registers) → [0..65535]."""
        return self._read_regs(3, addr, count, unit)

    def readInput(self, addr: int, count: int = 1, unit: Optional[int] = None) -> List[int]:
        """Function 04 (input registers) → [0..65535]."""
        return self._read_regs(4, addr, count, unit)

    def writeCoil(self, addr: int, value: int, unit: Optional[int] = None) -> None:
        """Function 05."""
        self._check(addr, 1, 1)
        self.request(5, struct.pack(">HH", addr, 0xFF00 if value else 0), unit)

    def writeRegister(self, addr: int, value: int, unit: Optional[int] = None) -> None:
        """Function 06 (value 0..65535; negative = two's complement)."""
        self._check(addr, 1, 1)
        self.request(6, struct.pack(">HH", addr, self._reg(value)), unit)

    def writeCoils(self, addr: int, values: Sequence[int], unit: Optional[int] = None) -> None:
        """Function 15."""
        values = list(values)
        self._check(addr, len(values), WRITE_LIMIT[15])
        data = bytearray((len(values) + 7) // 8)
        for i, b in enumerate(values):
            if b:
                data[i // 8] |= 1 << (i % 8)
        self.request(15, struct.pack(">HHB", addr, len(values), len(data)) + bytes(data), unit)

    def writeRegisters(self, addr: int, values: Sequence[int], unit: Optional[int] = None) -> None:
        """Function 16."""
        values = [self._reg(v) for v in values]
        self._check(addr, len(values), WRITE_LIMIT[16])
        self.request(16, struct.pack(">HHB", addr, len(values), 2 * len(values))
                     + b"".join(struct.pack(">H", v) for v in values), unit)

    @staticmethod
    def _reg(v: int) -> int:
        v = int(v)
        if not -0x8000 <= v <= 0xFFFF:
            raise ValueError(f"register value {v} out of range")
        return v & 0xFFFF

    def scan(self, first: int = 1, last: int = 247, fn: int = 3, addr: int = 0,
             timeout: Optional[float] = None) -> List[int]:
        """Unit ids that answer one read (an exception answer counts — a device is there)."""
        found, old = [], self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            for unit in range(int(first), int(last) + 1):
                try:
                    self.request(fn, struct.pack(">HH", addr, 1), unit)
                    found.append(unit)
                except ModbusException:
                    found.append(unit)
                except ModbusError:
                    pass
        finally:
            self.timeout = old
        return found


class ModbusRTU(ModbusMaster):
    """Modbus RTU on a serial port (RS-485 / RS-232 / USB adapter)."""

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 9600, unit: int = 1, timeout: float = 0.5,
                 parity: str = "N", bytesize: int = 8, stopbits: int = 1, retries: int = 0) -> None:
        super().__init__(unit, timeout, retries)
        self.port, self.baud, self.parity, self.bytesize, self.stopbits = port, int(baud), parity, bytesize, stopbits

    def __repr__(self) -> str:
        return f"ModbusRTU({self.port!r}, {self.baud})"

    def _open(self):
        try:
            import serial
        except ImportError:
            raise ModbusError("pyserial is not installed (apt install python3-serial)")
        try:
            return serial.Serial(self.port, self.baud, bytesize=self.bytesize, parity=self.parity,
                                 stopbits=self.stopbits, timeout=self.timeout, write_timeout=2, exclusive=True)
        except (serial.SerialException, OSError) as e:
            raise ModbusError(f"cannot open {self.port}: {e}")

    def _write(self, data: bytes) -> None:
        self._dev.write(data)
        self._dev.flush()

    def _drain(self) -> bool:
        self._dev.reset_input_buffer()
        return True

    def _read(self, n: int, deadline: float) -> bytes:
        buf = b""
        while len(buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            self._dev.timeout = left
            buf += self._dev.read(n - len(buf))
        return buf

    def _gap(self) -> float:
        """Silent interval between frames: 3.5 characters, at least 1.75 ms (Modbus over serial line spec)."""
        bits = 1 + self.bytesize + (0 if self.parity == "N" else 1) + self.stopbits
        return max(3.5 * bits / self.baud, 0.00175)


class _Socket(ModbusMaster):
    DEFAULT_PORT = 502

    def __init__(self, host: str, port: Optional[int] = None, unit: int = 1, timeout: float = 1.0,
                 retries: int = 0) -> None:
        super().__init__(unit, timeout, retries)
        self.host, self.port = host, int(port or self.DEFAULT_PORT)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.host!r}, {self.port})"

    def _open(self):
        try:
            if self.STREAM:
                s = socket.create_connection((self.host, self.port), timeout=max(self.timeout, 1.0))
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect((socket.gethostbyname(self.host), self.port))
            s.settimeout(self.timeout)
            return s
        except OSError as e:
            raise ModbusError(f"cannot connect to {self.host}:{self.port}: {e.strerror or e}")


class ModbusTCP(_Socket):
    """Modbus TCP (MBAP header), port 502."""
    RTU, STREAM = False, True


class ModbusUDP(_Socket):
    """Modbus TCP frames in UDP datagrams, port 502."""
    RTU, STREAM = False, False


class ModbusRTUoverTCP(_Socket):
    """RTU frames (with CRC) through a TCP serial server / gateway (often port 4001, 8899 …)."""
    RTU, STREAM = True, True


class ModbusRTUoverUDP(_Socket):
    """RTU frames in UDP datagrams."""
    RTU, STREAM = True, False


if __name__ == "__main__":
    # Read-only check: python3 instruments/modbus.py /dev/ttyUSB0 115200 [unit] [addr] [count]   (function 03)
    import sys
    a = sys.argv[1:]
    mb = ModbusRTU(a[0] if a else "/dev/ttyUSB0", int(a[1]) if len(a) > 1 else 9600, unit=int(a[2]) if len(a) > 2 else 1)
    regs = mb.readHolding(int(a[3]) if len(a) > 3 else 0, int(a[4]) if len(a) > 4 else 10)
    print(regs)
    print(mb.last)
    mb.close()
