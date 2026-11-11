"""OWON bench multimeter (XDM1041, XDM1241, XDM2041, XDM3051 …) — SCPI over USB-serial or LAN.

    from instruments.owon_xdm import OWON_XDM

    dmm = OWON_XDM(serial="/dev/ttyUSB0")        # USB (CH340 / CP210x), 115200 8N1
    dmm = OWON_XDM(host="192.168.1.60")          # LAN models, raw SCPI socket (port 3000 — check the meter's menu)
    v = dmm.getVoltDC()                          # V
    r = dmm.getResistance()                      # Ω, None on overload ("OVLD" / open input)

The function is switched only when it changes (relays click, the reading needs time to settle), then the first
reading after the switch is thrown away. The SCPI words differ a little between OWON series: they are in
``OWON_XDM.COMMANDS`` — adapt one there (or in your script: ``dmm.COMMANDS["read"] = "MEAS?"``) if your model
answers "command error".
"""
import time
from typing import Optional

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.scpi import ScpiInstrument


class OWON_XDM(ScpiInstrument):
    DEFAULT_PORT = 3000
    DEFAULT_BAUD = 115200
    WRITE_DELAY = 0.05

    COMMANDS = {
        "vdc": "CONF:VOLT:DC", "vac": "CONF:VOLT:AC", "idc": "CONF:CURR:DC", "iac": "CONF:CURR:AC",
        "res": "CONF:RES", "cont": "CONF:CONT", "diode": "CONF:DIOD", "cap": "CONF:CAP", "freq": "CONF:FREQ",
        "temp": "CONF:TEMP:RTD PT100",
        "read": "MEAS1?",                # main display value
        "rate": "RATE {}",               # S (slow, most accurate) / M / F (fast)
        "auto": "AUTO",                  # auto range
        "local": "SYST:LOC",             # front panel keys back
    }
    SETTLE = {"cap": 2.0, "res": 0.8, "temp": 1.0}       # s after a function switch (default 0.5)

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, serial: Optional[str] = None,
                 baud: Optional[int] = None, timeout: float = 3.0) -> None:
        if not host and not serial:
            serial = "/dev/ttyUSB0"
        super().__init__(host=host, port=port, serial=serial, baud=baud, timeout=timeout)
        self.COMMANDS = dict(type(self).COMMANDS)       # per instance: a script may adapt one word
        self._func = None

    # ── Setup ───────────────────────────────────────────────

    def configure(self, func: str, rng: Optional[str] = None) -> None:
        """Select a function: vdc vac idc iac res cont diode cap freq temp; ``rng`` = a range word of the meter
        (e.g. "5" for 5 V) or None = auto range. Waits until the reading has settled."""
        if func not in self.COMMANDS or func in ("read", "rate", "auto", "local"):
            raise ValueError(f"unknown function {func!r}")
        key = (func, rng)
        if key == self._func:
            return
        self.write(self.COMMANDS[func] + (f" {rng}" if rng else ""))
        if rng is None and func not in ("cont", "diode"):
            try:
                self.write(self.COMMANDS["auto"])
            except Exception:
                pass
        self._func = key
        time.sleep(self.SETTLE.get(func, 0.5))
        try:
            self.read()                                  # first value after a switch is often stale
        except Exception:
            pass

    def setRate(self, rate: str = "S") -> None:
        """Reading rate: S (slow, best resolution), M, F (fast)."""
        rate = rate.upper()
        if rate not in ("S", "M", "F"):
            raise ValueError("rate S, M or F")
        self.write(self.COMMANDS["rate"].format(rate))

    def local(self) -> None:
        """Give the front panel back (end of the test)."""
        self.write(self.COMMANDS["local"])
        self._func = None

    # ── Readings ────────────────────────────────────────────

    def read(self) -> Optional[float]:
        """The value on the display in the current function (None on overload)."""
        return self.queryFloat(self.COMMANDS["read"])

    def readAvg(self, n: int = 5, delay: float = 0.2) -> Optional[float]:
        """Mean of n readings (overloads skipped; None if all overloaded)."""
        vals = []
        for _ in range(n):
            v = self.read()
            if v is not None:
                vals.append(v)
            time.sleep(delay)
        return sum(vals) / len(vals) if vals else None

    def _measure(self, func: str, rng: Optional[str]) -> Optional[float]:
        self.configure(func, rng)
        return self.read()

    def getVoltDC(self, rng: Optional[str] = None) -> Optional[float]:
        """DC voltage, V."""
        return self._measure("vdc", rng)

    def getVoltAC(self, rng: Optional[str] = None) -> Optional[float]:
        """AC voltage (RMS), V."""
        return self._measure("vac", rng)

    def getCurrentDC(self, rng: Optional[str] = None) -> Optional[float]:
        """DC current, A (mind the input jack)."""
        return self._measure("idc", rng)

    def getCurrentAC(self, rng: Optional[str] = None) -> Optional[float]:
        """AC current (RMS), A."""
        return self._measure("iac", rng)

    def getResistance(self, rng: Optional[str] = None) -> Optional[float]:
        """Resistance, Ω (None = open / overload)."""
        return self._measure("res", rng)

    def getContinuity(self) -> Optional[float]:
        """Continuity test resistance, Ω (None = open)."""
        return self._measure("cont", None)

    def getDiode(self) -> Optional[float]:
        """Diode forward voltage, V (None = open / reversed)."""
        return self._measure("diode", None)

    def getCapacitance(self, rng: Optional[str] = None) -> Optional[float]:
        """Capacitance, F."""
        return self._measure("cap", rng)

    def getFrequency(self) -> Optional[float]:
        """Frequency, Hz."""
        return self._measure("freq", None)

    def getTemperature(self) -> Optional[float]:
        """Temperature with the PT100 probe, °C."""
        return self._measure("temp", None)


