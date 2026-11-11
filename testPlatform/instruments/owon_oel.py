"""OWON DC electronic load (OEL1515, OEL1530, OEL3120 …) — SCPI over USB-serial or LAN.

    from instruments.owon_oel import OWON_OEL

    load = OWON_OEL(serial="/dev/ttyUSB1")      # USB, 115200 8N1
    load = OWON_OEL(host="192.168.1.61")        # LAN models (raw SCPI socket, port 3000 — check the menu)
    load.setCC(1.5)                              # constant current 1.5 A (input stays off)
    load.on()
    v, i, p = load.getVoltage(), load.getCurrent(), load.getPower()
    load.off()                                   # always in finalize()

Modes: CC (A), CV (V), CR (Ω), CP (W). Setting a mode never switches the input on by itself — call on() or use
setup(mode, value). The SCPI words are in ``OWON_OEL.COMMANDS``; adapt one if your model answers "command error".
"""
import time
from typing import Optional

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.scpi import InstrumentError, ScpiInstrument

MODES = {"CC": ("CURR", "current"), "CV": ("VOLT", "voltage"), "CR": ("RES", "resistance"), "CP": ("POW", "power")}


class OWON_OEL(ScpiInstrument):
    DEFAULT_PORT = 3000
    DEFAULT_BAUD = 115200
    WRITE_DELAY = 0.05

    COMMANDS = {
        "on": "INP ON", "off": "INP OFF", "state": "INP?",
        "mode": "FUNC {}", "mode?": "FUNC?",           # {} = CURR / VOLT / RES / POW
        "CURR": "CURR {:g}", "VOLT": "VOLT {:g}", "RES": "RES {:g}", "POW": "POW {:g}",
        "meas_v": "MEAS:VOLT?", "meas_i": "MEAS:CURR?", "meas_p": "MEAS:POW?",
        "local": "SYST:LOC",
    }

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, serial: Optional[str] = None,
                 baud: Optional[int] = None, timeout: float = 3.0) -> None:
        if not host and not serial:
            serial = "/dev/ttyUSB0"
        super().__init__(host=host, port=port, serial=serial, baud=baud, timeout=timeout)
        self.COMMANDS = dict(type(self).COMMANDS)

    # ── Input ───────────────────────────────────────────────

    def on(self) -> None:
        """Input on (the load starts sinking)."""
        self.write(self.COMMANDS["on"])

    def off(self) -> None:
        """Input off — use it in finalize()."""
        self.write(self.COMMANDS["off"])

    def isOn(self) -> bool:
        return self.query(self.COMMANDS["state"]).strip().upper() in ("1", "ON")

    # ── Modes ───────────────────────────────────────────────

    def _set(self, mode: str, value: float) -> None:
        word, what = MODES[mode]
        if float(value) < 0:
            raise ValueError(f"{what} must not be negative")
        self.write(self.COMMANDS["mode"].format(word))
        self.write(self.COMMANDS[word].format(float(value)))

    def setCC(self, amps: float) -> None:
        """Constant current, A."""
        self._set("CC", amps)

    def setCV(self, volts: float) -> None:
        """Constant voltage, V."""
        self._set("CV", volts)

    def setCR(self, ohms: float) -> None:
        """Constant resistance, Ω."""
        self._set("CR", ohms)

    def setCP(self, watts: float) -> None:
        """Constant power, W."""
        self._set("CP", watts)

    def setup(self, mode: str, value: float, on: bool = True) -> None:
        """Mode (CC / CV / CR / CP) + value, then input on (or leave it off)."""
        mode = mode.upper()
        if mode not in MODES:
            raise ValueError("mode CC, CV, CR or CP")
        self._set(mode, value)
        if on:
            self.on()

    def getMode(self) -> str:
        """CC, CV, CR or CP."""
        word = self.query(self.COMMANDS["mode?"]).strip().upper()
        for mode, (w, _) in MODES.items():
            if word.startswith(w):
                return mode
        raise InstrumentError(f"unknown mode answer {word!r}")

    # ── Measurements ────────────────────────────────────────

    def getVoltage(self) -> Optional[float]:
        """Input voltage, V."""
        return self.queryFloat(self.COMMANDS["meas_v"])

    def getCurrent(self) -> Optional[float]:
        """Input current, A."""
        return self.queryFloat(self.COMMANDS["meas_i"])

    def getPower(self) -> Optional[float]:
        """Input power, W."""
        return self.queryFloat(self.COMMANDS["meas_p"])

    def waitCurrent(self, target: float, tolerance: float = 0.05, timeout: float = 5.0) -> Optional[float]:
        """Wait until the measured current is within target ± tolerance; returns the last reading."""
        end = time.time() + timeout
        i = self.getCurrent()
        while (i is None or abs(i - target) > tolerance) and time.time() < end:
            time.sleep(0.1)
            i = self.getCurrent()
        return i

    def local(self) -> None:
        """Give the front panel back."""
        self.write(self.COMMANDS["local"])


