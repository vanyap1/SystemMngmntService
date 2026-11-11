"""Driver for the single-channel "PSU Ethernet Controller" (FW 2.0, SCPI-99) that drives a 30 V / 5 A bench supply
through its REM line — PSU_CUSTOM305.

Raw SCPI over TCP port 8080, one command per connection (like PSU_CUSTOM6020): the answer ends with CR LF and the
controller closes the connection. Setting commands answer "OK"; refused ones "ERROR: <code>,<text>" → PsuError.
Command reference: http://<ip>/ → SCPI.

    from instruments.psu_custom305 import PSU_CUSTOM305

    psu = PSU_CUSTOM305("192.168.1.99")            # host, port=8080, timeout=3.0, retries=5, auto_remote=True
    psu.setup(12.0, 0.5)                           # setpoints + output on (takes over the supply: REM on)
    v, i, w = psu.measureAll()
    psu.off()
    psu.local()                                    # hand the supply back to its front panel

REM: without it the controller only measures — setpoints and OUTP ON are refused with -221. With
``auto_remote=True`` (default) the first refused setting command switches REM on and is sent again; REM on starts
with the output OFF. One channel only, so the functions take no channel number.
"""
import time
from typing import Dict, List, Optional, Tuple

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.psu_tcp import OneShotTcpPsu, PsuError

DATA_FIELDS = ("voltage", "current", "power", "set_voltage", "set_current", "output", "remote", "adc_ok", "dac_ok",
               "dig_out", "dig_in", "v_max", "i_max", "cal")


class PSU_CUSTOM305(OneShotTcpPsu):
    DEFAULT_HOST = "192.168.1.99"

    def __init__(self, host: Optional[str] = None, port: int = OneShotTcpPsu.DEFAULT_PORT, timeout: float = 3.0,
                 retries: int = 5, auto_remote: bool = True) -> None:
        super().__init__(host, port, timeout, retries)
        self.auto_remote = auto_remote

    # ── Raw ─────────────────────────────────────────────────

    def command(self, cmd: str) -> str:
        """Send a setting command; with auto_remote a "-221 REM off" refusal switches REM on and retries once."""
        try:
            return self.query(cmd)
        except PsuError as e:
            if not (self.auto_remote and "-221" in str(e)):
                raise
        self.query("SYST:REM ON")
        return self.query(cmd)

    def _floats(self, cmd: str) -> List[float]:
        answer = self.query(cmd)
        try:
            return [float(x) for x in answer.split(",")]
        except ValueError:
            raise PsuError(f"{cmd}: unexpected answer {answer!r}")

    def _bit(self, cmd: str) -> int:
        answer = self.query(cmd).strip()
        try:
            return int(answer)
        except ValueError:
            raise PsuError(f"{cmd}: unexpected answer {answer!r}")

    # ── Identity / system ───────────────────────────────────

    def identify(self) -> str:
        """*IDN? — "PSU-ETH,<name>,0,FW 2.0 <date>"."""
        return self.query("*IDN?")

    def ping(self) -> bool:
        """The controller answers."""
        try:
            return self.query("*IDN?").startswith("PSU-ETH")
        except PsuError:
            return False

    def info(self) -> Dict[str, str]:
        """SYSTem:INFO? — firmware, reset cause, meter, DAC, network as a dict."""
        out = {}
        for ln in self.query("SYST:INFO?").splitlines():
            k, sep, v = ln.partition("=")
            if sep:
                out[k.strip()] = v.strip()
        return out

    def selfTest(self) -> bool:
        """*TST? — True when the meter and the DAC are OK."""
        return self._bit("*TST?") == 0

    def reset(self) -> None:
        """*RST — output off, setpoints 0 (REM unchanged)."""
        self.command("*RST")

    def clearStatus(self) -> None:
        """*CLS — clear the error queue."""
        self.query("*CLS")

    def errors(self) -> List[str]:
        """Read the error queue until it is empty; [] = no errors."""
        out = []
        for _ in range(10):
            e = self.query("SYST:ERR?")
            if not e or e.startswith("0") or e.startswith("+0"):
                break
            out.append(e)
        return out

    # ── Remote / local ──────────────────────────────────────

    def setRemote(self, enabled: bool = True) -> None:
        """REM on: the controller takes over the supply (output starts OFF); off: the front panel controls it."""
        self.query("SYST:REM ON" if enabled else "SYST:REM OFF")

    def local(self) -> None:
        """Hand the supply back to its front panel (SYSTem:LOCal)."""
        self.query("SYST:LOC")

    def isRemote(self) -> bool:
        return self._bit("SYST:REM?") == 1

    # ── Setpoints / output ──────────────────────────────────

    def setVoltage(self, volts: float) -> None:
        self.command(f"VOLT {float(volts):.4f}")

    def setCurrent(self, amps: float) -> None:
        self.command(f"CURR {float(amps):.4f}")

    def apply(self, volts: float, amps: Optional[float] = None) -> None:
        """Both setpoints in one command (APPLy)."""
        self.command(f"APPL {float(volts):.4f}" + ("" if amps is None else f",{float(amps):.4f}"))

    def getSetVoltage(self) -> float:
        return self._floats("VOLT?")[0]

    def getSetCurrent(self) -> float:
        return self._floats("CURR?")[0]

    def getLimits(self) -> Tuple[float, float]:
        """Highest allowed setpoints (v_max, i_max) from the controller settings."""
        return self._floats("VOLT:LIM?")[0], self._floats("CURR:LIM?")[0]

    def on(self) -> None:
        self.command("OUTP ON")

    def off(self) -> None:
        """Output off (DAC to 0 V). Harmless without REM: nothing is switched then."""
        if self.isRemote():
            self.command("OUTP OFF")

    def setOutput(self, enabled: bool) -> None:
        self.on() if enabled else self.off()

    def isOn(self) -> bool:
        return self._bit("OUTP?") == 1

    def setup(self, volts: float, amps: float, on: bool = True) -> None:
        """Setpoints and (optionally) the output on in one call."""
        self.apply(volts, amps)
        if on:
            self.on()

    # ── Measurements ────────────────────────────────────────

    def getVoltage(self) -> float:
        """Measured output voltage, V (0.5 s average)."""
        return self._floats("MEAS:VOLT?")[0]

    def getCurrent(self) -> float:
        return self._floats("MEAS:CURR?")[0]

    def getPower(self) -> float:
        return self._floats("MEAS:POW?")[0]

    def measureAll(self) -> Tuple[float, float, float]:
        """(volts, amps, watts) from one request."""
        v = self._floats("MEAS:ALL?")
        if len(v) < 3:
            raise PsuError(f"MEAS:ALL?: unexpected answer {v!r}")
        return v[0], v[1], v[2]

    def waitVoltage(self, target: float, tolerance: float = 0.1, timeout: float = 5.0) -> Optional[float]:
        """Poll the measured voltage until it is within ``tolerance`` of ``target``; the last value (None if never
        within the tolerance before ``timeout``)."""
        end = time.time() + timeout
        while True:
            v = self.getVoltage()
            if abs(v - target) <= tolerance:
                return v
            if time.time() >= end:
                return None
            time.sleep(0.3)

    def getData(self) -> Dict[str, object]:
        """Everything in one request (PSU:DATA?) as a dict — see DATA_FIELDS."""
        answer = self.query("PSU:DATA?")
        parts = answer.split(",")
        if len(parts) < len(DATA_FIELDS):
            raise PsuError(f"PSU:DATA?: unexpected answer {answer!r}")
        out = {}
        for k, v in zip(DATA_FIELDS, parts):
            if k == "cal":
                out[k] = v.strip()
            elif k in ("output", "remote", "adc_ok", "dac_ok", "dig_out", "dig_in"):
                out[k] = int(v)
            else:
                out[k] = float(v)
        for k in ("output", "remote", "adc_ok", "dac_ok"):
            out[k] = bool(out[k])
        return out

    # ── Digital IO of the controller (O1..O3, IN1..IN3) ─────

    def digOut(self, n: int, value: int) -> None:
        """Switch output O<n> (1..3)."""
        self.query(f"DIG:OUTP {self._io(n)},{1 if value else 0}")

    def digOutAll(self, mask: int) -> None:
        """All outputs at once, bit0 = O1."""
        if not 0 <= int(mask) <= 7:
            raise ValueError("mask 0..7")
        self.query(f"DIG:OUTP:ALL {int(mask)}")

    def digOutRead(self, n: Optional[int] = None) -> int:
        """One output level (0/1), or all outputs as bits without ``n``."""
        return self._bit("DIG:OUTP?" if n is None else f"DIG:OUTP? {self._io(n)}")

    def digIn(self, n: Optional[int] = None) -> int:
        """One input level (0/1), or all inputs as bits (bit0 = IN1) without ``n``."""
        return self._bit("DIG:INP?" if n is None else f"DIG:INP? {self._io(n)}")

    @staticmethod
    def _io(n: int) -> int:
        if n not in (1, 2, 3):
            raise ValueError("digital IO 1..3")
        return n

    # ── EXT_IO modules ──────────────────────────────────────

    def ioList(self) -> List[dict]:
        """Configured EXT_IO modules: [{n, type, addr, name, labels}] ([] for NONE)."""
        out = []
        for ln in self.query("EXTIO:LIST?").splitlines():
            f = ln.strip().split("|")
            if len(f) < 4 or not f[0].strip().isdigit():
                continue
            out.append({"n": int(f[0]), "type": f[1], "addr": f[2], "name": f[3],
                        "labels": [x for x in f[4:] if x]})
        return out

    def ioState(self, module: Optional[int] = None) -> str:
        """Raw state line(s) of all / one module: n|type|addr|online|pins|setpoint."""
        return self.query("EXTIO:STATE?" if module is None else f"EXTIO:STATE? {int(module)}")

    def ioIn(self, module: int, ch: int) -> int:
        return self._bit(f"EXTIO:IN? {int(module)},{int(ch)}")

    def ioOutRead(self, module: int, ch: int) -> int:
        return self._bit(f"EXTIO:OUT? {int(module)},{int(ch)}")

    def ioOut(self, module: int, ch: int, value: int) -> int:
        """Set one output; returns the actual level."""
        return self._bit(f"EXTIO:OUT {int(module)},{int(ch)},{1 if value else 0}")

    def ioOutAll(self, module: int, mask: int) -> int:
        """All outputs of a module from a bit mask; returns the controller's answer as a number."""
        return self._bit(f"EXTIO:OUT:ALL {int(module)},{int(mask):X}")


if __name__ == "__main__":
    # Read-only check: nothing is switched or changed.  python3 instruments/psu_custom305.py [host]
    import sys
    psu = PSU_CUSTOM305(sys.argv[1] if len(sys.argv) > 1 else PSU_CUSTOM305.DEFAULT_HOST)
    print(psu.identify())
    print("remote:", psu.isRemote(), " output:", psu.isOn(), " limits:", psu.getLimits())
    print("V, A, W:", psu.measureAll())
    print("data:", psu.getData())
    print("digital in / out:", psu.digIn(), psu.digOutRead())
    print("EXT_IO:", psu.ioList())
