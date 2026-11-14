"""Siglent SDL1000X DC electronic loads (SDL1020X, SDL1030X …) over LAN — common driver.
Scripts use the model class: instruments/siglent_sdl1020x.py → SIGLENT_SDL1020X.

    from instruments.siglent_sdl1020x import SIGLENT_SDL1020X

    load = SIGLENT_SDL1020X("192.168.1.72")       # host, port=5025 (raw SCPI socket), timeout=3.0
    load.setCC(0.5)                                # constant current 0.5 A (the input stays as it is)
    load.on()
    v, i, p = load.measureAll()
    load.off()                                     # always in finalize()

Modes: CC (A), CV (V), CR (Ω), CP (W). Setting a mode never switches the input on — call on() or use
setup(mode, value). Every level is read back after it is written (InstrumentError if the load did not take it),
the input state too. Error answers end with an extra empty line (skipped: SKIP_EMPTY).
Command reference: Siglent "SDL1000X Programming Guide".
"""
import time
from typing import Dict, Optional, Tuple

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.scpi import InstrumentError, ScpiInstrument  # noqa: E402

MODES = {"CC": "CURRent", "CV": "VOLTage", "CR": "RESistance", "CP": "POWer"}
_FUNC_NAMES = {"CURRENT": "CC", "VOLTAGE": "CV", "RESISTANCE": "CR", "POWER": "CP"}


class SiglentSDL(ScpiInstrument):
    """Common driver of the SDL1000X series; MODEL / V_MAX / I_MAX / P_MAX come from the model class."""
    DEFAULT_PORT = 5025
    WRITE_DELAY = 0.05
    SKIP_EMPTY = True
    V_MAX = 150.0
    I_MAX = 30.0
    P_MAX = 200.0

    def __init__(self, host: str = "192.168.1.72", port: int = DEFAULT_PORT, timeout: float = 3.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)

    def _number(self, cmd: str) -> float:
        v = self.queryFloat(cmd)
        if v is None:
            raise InstrumentError(f"{cmd}: no value")
        return v

    def _set(self, cmd: str, value: float) -> None:
        """Write ``cmd value`` and read ``cmd?`` back (one retry: a dropped command)."""
        for _ in (1, 2):
            self.write(f"{cmd} {value:.6g}")
            got = self._number(f"{cmd}?")
            if abs(got - value) <= max(abs(value) * 1e-4, 1e-4):
                return
        raise InstrumentError(f"{cmd} {value:g}: the load did not take the value (reads {got:g})")

    def _check(self, what: str, value: float, top: float) -> float:
        value = float(value)
        if not 0 <= value <= top:
            raise ValueError(f"{what} 0..{top:g}")
        return value

    # ── Mode and level ──────────────────────────────────────

    def setMode(self, mode: str) -> None:
        """CC, CV, CR or CP (the input keeps its state)."""
        mode = mode.upper()
        if mode not in MODES:
            raise ValueError("mode: CC, CV, CR or CP")
        for _ in (1, 2):
            self.write(f":SOUR:FUNC {MODES[mode]}")
            if self.getMode() == mode:
                return
        raise InstrumentError(f"mode {mode}: the load did not switch")

    def getMode(self) -> str:
        """CC, CV, CR or CP (or the raw answer for other functions, e.g. "LED")."""
        answer = self.query(":SOUR:FUNC?").strip().upper()
        return _FUNC_NAMES.get(answer, answer)

    def setCC(self, amps: float) -> None:
        """Constant current mode, A."""
        amps = self._check("current", amps, self.I_MAX)
        self.setMode("CC")
        self._set(":SOUR:CURR:LEV:IMM", amps)

    def setCV(self, volts: float) -> None:
        """Constant voltage mode, V (the load sinks what it takes to hold the voltage)."""
        volts = self._check("voltage", volts, self.V_MAX)
        self.setMode("CV")
        self._set(":SOUR:VOLT:LEV:IMM", volts)

    def setCR(self, ohms: float) -> None:
        """Constant resistance mode, Ω."""
        ohms = self._check("resistance", ohms, 10000)
        self.setMode("CR")
        self._set(":SOUR:RES:LEV:IMM", ohms)

    def setCP(self, watts: float) -> None:
        """Constant power mode, W."""
        watts = self._check("power", watts, self.P_MAX)
        self.setMode("CP")
        self._set(":SOUR:POW:LEV:IMM", watts)

    def setup(self, mode: str, value: float, on: bool = True) -> None:
        """Mode + level (+ input on) in one call, e.g. setup("CC", 1.5)."""
        {"CC": self.setCC, "CV": self.setCV, "CR": self.setCR, "CP": self.setCP}[self._mode(mode)](value)
        if on:
            self.on()

    def getLevel(self, mode: Optional[str] = None) -> float:
        """Level of a mode (default: the current mode)."""
        return self._number(f":SOUR:{MODES[self._mode(mode or self.getMode())]}:LEV:IMM?")

    @staticmethod
    def _mode(mode: str) -> str:
        mode = (mode or "").upper()
        if mode not in MODES:
            raise ValueError("mode: CC, CV, CR or CP")
        return mode

    def setRange(self, irange: Optional[int] = None, vrange: Optional[int] = None) -> None:
        """Ranges of the present mode: current 5 / 30 A, voltage 36 / 150 V (the low range is more accurate)."""
        func = MODES[self._mode(self.getMode())]
        if irange is not None:
            self._set(f":SOUR:{func}:IRANG", float(irange))
        if vrange is not None:
            self._set(f":SOUR:{func}:VRANG", float(vrange))

    def setSlew(self, rise: float, fall: Optional[float] = None) -> None:
        """Current slew rate of CC mode, A/µs (fall = rise when omitted)."""
        self._set(":SOUR:CURR:SLEW:POS", float(rise))
        self._set(":SOUR:CURR:SLEW:NEG", float(rise if fall is None else fall))

    def setVon(self, volts: float, latch: bool = True) -> None:
        """Von: the load starts sinking only above this input voltage (latch: keeps sinking once started)."""
        self._set(":SOUR:VOLT:ON", float(volts))
        self.write(f":SOUR:VOLT:LATC:STAT {'ON' if latch else 'OFF'}")

    # ── Input ───────────────────────────────────────────────

    def on(self) -> None:
        self._input(True)

    def off(self) -> None:
        self._input(False)

    def setInput(self, enabled: bool) -> None:
        self._input(bool(enabled))

    def _input(self, enabled: bool) -> None:
        for _ in (1, 2):
            self.write(f":SOUR:INP:STAT {'ON' if enabled else 'OFF'}")
            if self.isOn() == enabled:
                return
        raise InstrumentError(f"input did not switch {'on' if enabled else 'off'}")

    def isOn(self) -> bool:
        return self.query(":SOUR:INP:STAT?").strip() in ("1", "ON")

    def short(self, enabled: bool) -> None:
        """Short the input (maximum current of the range!) — only with a current-limited source."""
        self.write(f":SOUR:SHOR:STAT {'ON' if enabled else 'OFF'}")

    # ── Measurements ────────────────────────────────────────

    def getVoltage(self) -> float:
        """Measured input voltage, V."""
        return self._number(":MEAS:VOLT?")

    def getCurrent(self) -> float:
        return self._number(":MEAS:CURR?")

    def getPower(self) -> float:
        return self._number(":MEAS:POW?")

    def getResistance(self) -> float:
        return self._number(":MEAS:RES?")

    def measureAll(self) -> Tuple[float, float, float]:
        """(volts, amps, watts)."""
        return self.getVoltage(), self.getCurrent(), self.getPower()

    def waitCurrent(self, target: float, tolerance: float = 0.02, timeout: float = 3.0) -> Optional[float]:
        """Poll the measured current until it is within ``tolerance`` A of ``target``; None on timeout."""
        end = time.time() + timeout
        while True:
            i = self.getCurrent()
            if abs(i - target) <= tolerance:
                return i
            if time.time() >= end:
                return None
            time.sleep(0.1)

    # ── Protection / sense ──────────────────────────────────

    def setCurrentProtection(self, amps: Optional[float], delay: float = 0.0) -> None:
        """Input off when the current exceeds ``amps`` for ``delay`` s; None switches the protection off."""
        if amps is None:
            self.write(":SOUR:CURR:PROT:STAT OFF")
            return
        self._set(":SOUR:CURR:PROT:LEV", self._check("current", amps, self.I_MAX))
        self._set(":SOUR:CURR:PROT:DEL", float(delay))
        self.write(":SOUR:CURR:PROT:STAT ON")

    def setPowerProtection(self, watts: Optional[float], delay: float = 0.0) -> None:
        """Input off when the power exceeds ``watts`` for ``delay`` s; None switches it off."""
        if watts is None:
            self.write(":SOUR:POW:PROT:STAT OFF")
            return
        self._set(":SOUR:POW:PROT:LEV", self._check("power", watts, self.P_MAX))
        self._set(":SOUR:POW:PROT:DEL", float(delay))
        self.write(":SOUR:POW:PROT:STAT ON")

    def protection(self) -> Dict[str, bool]:
        """Which protections are enabled: {"current": …, "power": …}."""
        return {"current": self.query(":SOUR:CURR:PROT:STAT?").strip() in ("1", "ON"),
                "power": self.query(":SOUR:POW:PROT:STAT?").strip() in ("1", "ON")}

    def setSense4Wire(self, enabled: bool) -> None:
        """Remote sense (4-wire) on / off."""
        self.write(f":SYST:SENS:STAT {'ON' if enabled else 'OFF'}")


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_sdl.py [ip]
    import sys
    ld = SiglentSDL(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.72")
    print(ld.idn())
    print("input:", ld.isOn(), " mode:", ld.getMode(), ld.getLevel(), " protection:", ld.protection())
    print("V, A, W:", ld.measureAll(), " errors:", ld.errors() or "none")
