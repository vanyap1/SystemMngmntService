"""Siglent SPD1000X single-channel programmable power supplies (SPD1168X, SPD1305X) over LAN — common driver.
Scripts use the model class: instruments/siglent_spd1305x.py → SIGLENT_SPD1305X.

    from instruments.siglent_spd1305x import SIGLENT_SPD1305X

    psu = SIGLENT_SPD1305X("192.168.1.74")        # host, port=5025 (raw SCPI socket), timeout=3.0
    psu.setup(12.0, 0.5)                           # setpoints (read back and checked) + output on
    v, i, w = psu.measureAll()
    psu.off()

Siglent specifics handled here:
* setting commands get no answer and are sometimes lost when sent back to back — the driver pauses after each
  one (WRITE_DELAY) and reads every setpoint back (InstrumentError if it did not take, after one retry);
* there is no OUTPut? query — the output state comes from SYSTem:STATus? (a hex word, see status());
* an error answer of SYSTem:ERRor? ends with an extra empty line — skipped (SKIP_EMPTY).
Command reference: Siglent "SPD1000X Programming Guide".
"""
import time
from typing import Dict, Optional, Tuple

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.scpi import InstrumentError, ScpiInstrument  # noqa: E402

STATUS_BITS = {"cc": 0, "output": 4, "wire4": 5, "timer": 6, "waveform": 8}     # SYSTem:STATus? bits


class SiglentSPD(ScpiInstrument):
    """Common driver of the SPD1000X series; MODEL / V_MAX / I_MAX come from the model class."""
    DEFAULT_PORT = 5025
    WRITE_DELAY = 0.05
    SKIP_EMPTY = True
    V_MAX = 32.0
    I_MAX = 6.0
    CH = "CH1"

    def __init__(self, host: str = "192.168.1.74", port: int = DEFAULT_PORT, timeout: float = 3.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)

    # ── Raw ─────────────────────────────────────────────────

    def _number(self, cmd: str) -> float:
        v = self.queryFloat(cmd)
        if v is None:
            raise InstrumentError(f"{cmd}: no value")
        return v

    def _set(self, cmd: str, query: str, value: float) -> None:
        for _ in (1, 2):
            self.write(f"{cmd} {value:.3f}")
            if abs(self._number(query) - value) < 0.0006:
                return
        raise InstrumentError(f"{cmd} {value:.3f}: the supply did not take the value (reads {self._number(query)})")

    # ── Identity ────────────────────────────────────────────

    def version(self) -> str:
        """Firmware version."""
        return self.query("SYST:VERS?")

    def network(self) -> Dict[str, str]:
        """LAN settings: ip, mask, gateway, dhcp."""
        return {"ip": self.query("IP?"), "mask": self.query("MASK?"), "gateway": self.query("GATE?"),
                "dhcp": self.query("DHCP?").split(":")[-1].strip()}

    # ── Setpoints / output ──────────────────────────────────

    def setVoltage(self, volts: float) -> None:
        """Voltage setpoint, V (checked against the model's range and read back)."""
        volts = float(volts)
        if not 0 <= volts <= self.V_MAX:
            raise ValueError(f"voltage 0..{self.V_MAX} V")
        self._set(f"{self.CH}:VOLT", f"{self.CH}:VOLT?", volts)

    def setCurrent(self, amps: float) -> None:
        """Current limit, A."""
        amps = float(amps)
        if not 0 <= amps <= self.I_MAX:
            raise ValueError(f"current 0..{self.I_MAX} A")
        self._set(f"{self.CH}:CURR", f"{self.CH}:CURR?", amps)

    def getSetVoltage(self) -> float:
        return self._number(f"{self.CH}:VOLT?")

    def getSetCurrent(self) -> float:
        return self._number(f"{self.CH}:CURR?")

    def on(self) -> None:
        self._output(True)

    def off(self) -> None:
        self._output(False)

    def setOutput(self, enabled: bool) -> None:
        self._output(bool(enabled))

    def _output(self, enabled: bool) -> None:
        for _ in (1, 2):
            self.write(f"OUTP {self.CH},{'ON' if enabled else 'OFF'}")
            if self.isOn() == enabled:
                return
        raise InstrumentError(f"output did not switch {'on' if enabled else 'off'}")

    def isOn(self) -> bool:
        return self.status()["output"]

    def setup(self, volts: float, amps: float, on: bool = True) -> None:
        """Setpoints and (optionally) the output on in one call."""
        self.setVoltage(volts)
        self.setCurrent(amps)
        if on:
            self.on()

    # ── Measurements ────────────────────────────────────────

    def getVoltage(self) -> float:
        """Measured output voltage, V."""
        return self._number("MEAS:VOLT?")

    def getCurrent(self) -> float:
        return self._number("MEAS:CURR?")

    def getPower(self) -> float:
        return self._number("MEAS:POWE?")

    def measureAll(self) -> Tuple[float, float, float]:
        """(volts, amps, watts)."""
        return self.getVoltage(), self.getCurrent(), self.getPower()

    def waitVoltage(self, target: float, tolerance: float = 0.1, timeout: float = 5.0) -> Optional[float]:
        """Poll the measured voltage until it is within ``tolerance`` of ``target``; None on timeout."""
        end = time.time() + timeout
        while True:
            v = self.getVoltage()
            if abs(v - target) <= tolerance:
                return v
            if time.time() >= end:
                return None
            time.sleep(0.2)

    # ── Status / modes ──────────────────────────────────────

    def status(self) -> Dict[str, object]:
        """SYSTem:STATus? decoded: {raw, cc (constant current), output, wire4 (4-wire sense), timer, waveform}."""
        answer = self.query("SYST:STAT?")
        try:
            raw = int(answer, 16)
        except ValueError:
            raise InstrumentError(f"SYST:STAT?: unexpected answer {answer!r}")
        out = {k: bool(raw >> b & 1) for k, b in STATUS_BITS.items()}
        out["raw"] = raw
        return out

    def isCC(self) -> bool:
        """True in constant current (the current limit is reached), False in constant voltage."""
        return self.status()["cc"]

    def setSense4Wire(self, enabled: bool) -> None:
        """4-wire (remote sense) or 2-wire mode (MODE:SET 4W / 2W)."""
        self.write(f"MODE:SET {'4W' if enabled else '2W'}")

    # ── Timer (sequence of up to 5 steps) ───────────────────

    def setTimer(self, step: int, volts: float, amps: float, seconds: float) -> None:
        """One step of the built-in timer sequence (1..5)."""
        self.write(f"TIME:SET {self.CH},{self._step(step)},{float(volts):.3f},{float(amps):.3f},{float(seconds):g}")

    def getTimer(self, step: int) -> Tuple[float, float, float]:
        """(volts, amps, seconds) of a timer step."""
        parts = [p for p in self.query(f"TIME:SET? {self.CH},{self._step(step)}").split(",") if p.strip()]
        try:
            return float(parts[0]), float(parts[1]), float(parts[2])
        except (IndexError, ValueError):
            raise InstrumentError(f"TIME:SET?: unexpected answer {parts!r}")

    def timer(self, enabled: bool) -> None:
        """Start / stop the timer sequence."""
        self.write(f"TIME {self.CH},{'ON' if enabled else 'OFF'}")

    @staticmethod
    def _step(step: int) -> int:
        if step not in (1, 2, 3, 4, 5):
            raise ValueError("timer step 1..5")
        return step

    # ── Memories ────────────────────────────────────────────

    def save(self, slot: int) -> None:
        """Store the setpoints into memory 1..5 (*SAV)."""
        self.write(f"*SAV {self._slot(slot)}")

    def recall(self, slot: int) -> None:
        """Load the setpoints from memory 1..5 (*RCL)."""
        self.write(f"*RCL {self._slot(slot)}")

    @staticmethod
    def _slot(slot: int) -> int:
        if slot not in (1, 2, 3, 4, 5):
            raise ValueError("memory 1..5")
        return slot


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_spd.py [ip]
    import sys
    p = SiglentSPD(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.74")
    print(p.idn())
    print("setpoints:", p.getSetVoltage(), "V", p.getSetCurrent(), "A   status:", p.status())
    print("V, A, W:", p.measureAll())
    print("network:", p.network(), " errors:", p.errors() or "none")
