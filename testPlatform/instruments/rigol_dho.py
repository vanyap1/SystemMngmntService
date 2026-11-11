"""Rigol DHO800 / DHO900 oscilloscope (DHO804, DHO814, DHO924 …) over LAN (LXI, raw SCPI socket :5555).

    from instruments.rigol_dho924 import RIGOL_DHO924    # or rigol_dho804 / RIGOL_DHO804 — same functions

    scope = RIGOL_DHO924("192.168.1.146")       # host, port=5555, timeout=5.0
    scope.autoset()
    vpp = scope.getVoltPkPk(1)                   # V, None when the scope cannot measure (no signal)
    f = scope.getFrequency(1)                    # Hz

Channels are 1…4. Measurements return float or None (the scope's "invalid" 9.9E37) — numericLimitTest turns None
into an ERROR row. Settings commands raise InstrumentError when the scope reports an error only if you call
errors() / checkErrors(); the scope itself never answers a setting command.
Command reference: Rigol "DHO800/DHO900 Programming Guide".
"""
import time
from typing import List, Optional, Tuple

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.scpi import InstrumentError, ScpiInstrument

MEAS_ITEMS = ("VMAX", "VMIN", "VPP", "VTOP", "VBASe", "VAMP", "VAVG", "VRMS", "OVERshoot", "PREShoot", "MARea",
              "MPARea", "PERiod", "FREQuency", "RTIMe", "FTIMe", "PWIDth", "NWIDth", "PDUTy", "NDUTy", "TVMAX",
              "TVMIN", "PSLewrate", "NSLewrate", "VUPPer", "VMID", "VLOWer", "VARiance", "PVRMs", "PPULses",
              "NPULses", "PEDGes", "NEDGes")


class RigolScope(ScpiInstrument):
    """Common driver of the DHO800 / DHO900 series; scripts use the model classes (rigol_dho804, rigol_dho924)."""
    DEFAULT_PORT = 5555
    MODEL = ""                                           # model in *IDN?, checked by checkModel()

    def __init__(self, host: str = "192.168.1.146", port: int = DEFAULT_PORT, timeout: float = 5.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)

    @staticmethod
    def _ch(ch) -> str:
        if isinstance(ch, str):                          # "CHAN1", "MATH1" … passed through
            return ch
        if ch not in (1, 2, 3, 4):
            raise ValueError("channel must be 1…4")
        return f"CHANnel{ch}"

    def checkModel(self) -> str:
        """*IDN? model; InstrumentError if it is not the model of this class (a wrong IP of another scope)."""
        parts = self.idn().split(",")
        model = parts[1].strip() if len(parts) > 1 else ""
        if self.MODEL and model.upper() != self.MODEL:
            raise InstrumentError(f"{self!r}: {model or 'unknown'} answers, {self.MODEL} expected")
        return model

    def checkErrors(self) -> None:
        """Raise InstrumentError if the scope's error queue is not empty (call it after a group of settings)."""
        errs = self.errors()
        if errs:
            raise InstrumentError("; ".join(errs))

    # ── Acquisition ─────────────────────────────────────────

    def autoset(self, wait: float = 3.0) -> None:
        """AUTO: find the signals and set scale, timebase and trigger (takes a few seconds)."""
        self.write(":AUToset")
        time.sleep(wait)

    def run(self) -> None:
        self.write(":RUN")

    def stop(self) -> None:
        self.write(":STOP")

    def single(self) -> None:
        """Arm one acquisition (single sweep)."""
        self.write(":SINGle")

    def forceTrigger(self) -> None:
        """Trigger now, whatever the trigger condition."""
        self.write(":TFORce")

    def clear(self) -> None:
        """Clear the waveforms on the screen."""
        self.write(":CLEar")

    def triggerStatus(self) -> str:
        """TD (triggered), WAIT, RUN, AUTO or STOP."""
        return self.query(":TRIGger:STATus?")

    def waitTriggered(self, timeout: float = 5.0) -> bool:
        """After single(): wait until the acquisition is complete (status STOP); False on timeout."""
        end = time.time() + timeout
        time.sleep(0.05)
        while time.time() < end:
            if self.triggerStatus() == "STOP":
                return True
            time.sleep(0.05)
        return False

    # ── Vertical ────────────────────────────────────────────

    def setChannel(self, ch: int, on: bool = True) -> None:
        """Show / hide a channel."""
        self.write(f":{self._ch(ch)}:DISPlay {1 if on else 0}")

    def setScale(self, ch: int, volts_per_div: float) -> None:
        self.write(f":{self._ch(ch)}:SCALe {float(volts_per_div):g}")

    def getScale(self, ch: int) -> float:
        return self.queryFloat(f":{self._ch(ch)}:SCALe?")

    def setOffset(self, ch: int, volts: float) -> None:
        self.write(f":{self._ch(ch)}:OFFSet {float(volts):g}")

    def setCoupling(self, ch: int, coupling: str = "DC") -> None:
        """DC, AC or GND."""
        coupling = coupling.upper()
        if coupling not in ("DC", "AC", "GND"):
            raise ValueError("coupling: DC, AC or GND")
        self.write(f":{self._ch(ch)}:COUPling {coupling}")

    def setProbe(self, ch: int, ratio: float = 10) -> None:
        """Probe attenuation (1, 10, 100 …)."""
        self.write(f":{self._ch(ch)}:PROBe {float(ratio):g}")

    def setBandwidthLimit(self, ch: int, on: bool = True) -> None:
        """20 MHz bandwidth limit on / off."""
        self.write(f":{self._ch(ch)}:BWLimit {'20M' if on else 'OFF'}")

    # ── Horizontal ──────────────────────────────────────────

    def setTimebase(self, seconds_per_div: float) -> None:
        self.write(f":TIMebase:MAIN:SCALe {float(seconds_per_div):g}")

    def getTimebase(self) -> float:
        return self.queryFloat(":TIMebase:MAIN:SCALe?")

    def setTimeOffset(self, seconds: float) -> None:
        self.write(f":TIMebase:MAIN:OFFSet {float(seconds):g}")

    def getSampleRate(self) -> float:
        """Current sample rate, Sa/s."""
        return self.queryFloat(":ACQuire:SRATe?")

    # ── Trigger ─────────────────────────────────────────────

    def setTrigger(self, ch: int = 1, level: float = 0.0, slope: str = "POS", sweep: str = "AUTO") -> None:
        """Edge trigger on a channel: level in V, slope POS / NEG / RFAL, sweep AUTO / NORM / SING."""
        slope, sweep = slope.upper(), sweep.upper()
        if slope not in ("POS", "NEG", "RFAL") or sweep not in ("AUTO", "NORM", "SING"):
            raise ValueError("slope POS/NEG/RFAL, sweep AUTO/NORM/SING")
        self.write(":TRIGger:MODE EDGE")
        self.write(f":TRIGger:EDGE:SOURce {self._ch(ch)}")
        self.write(f":TRIGger:EDGE:SLOPe {slope}")
        self.write(f":TRIGger:EDGE:LEVel {float(level):g}")
        self.write(f":TRIGger:SWEep {sweep}")

    def setTriggerLevel(self, level: float) -> None:
        self.write(f":TRIGger:EDGE:LEVel {float(level):g}")

    # ── Measurements ────────────────────────────────────────

    def measure(self, item: str, ch: int = 1) -> Optional[float]:
        """Any measurement item of the scope (VPP, FREQuency, RTIMe … see MEAS_ITEMS); None = cannot measure."""
        return self.queryFloat(f":MEASure:ITEM? {item},{self._ch(ch)}")

    def measureAvg(self, item: str, ch: int = 1, n: int = 5, delay: float = 0.2) -> Optional[float]:
        """Mean of n readings (None values skipped; None if all were invalid)."""
        vals = []
        for _ in range(n):
            v = self.measure(item, ch)
            if v is not None:
                vals.append(v)
            time.sleep(delay)
        return sum(vals) / len(vals) if vals else None

    def getVoltPkPk(self, ch: int = 1) -> Optional[float]:
        """Peak-to-peak voltage, V."""
        return self.measure("VPP", ch)

    def getVoltMax(self, ch: int = 1) -> Optional[float]:
        return self.measure("VMAX", ch)

    def getVoltMin(self, ch: int = 1) -> Optional[float]:
        return self.measure("VMIN", ch)

    def getVoltAmplitude(self, ch: int = 1) -> Optional[float]:
        """Top − base, V."""
        return self.measure("VAMP", ch)

    def getVoltAvg(self, ch: int = 1) -> Optional[float]:
        return self.measure("VAVG", ch)

    def getVoltRms(self, ch: int = 1) -> Optional[float]:
        return self.measure("VRMS", ch)

    def getFrequency(self, ch: int = 1) -> Optional[float]:
        """Hz."""
        return self.measure("FREQuency", ch)

    def getPeriod(self, ch: int = 1) -> Optional[float]:
        """s."""
        return self.measure("PERiod", ch)

    def getDutyCycle(self, ch: int = 1) -> Optional[float]:
        """Positive duty cycle, % (0…100)."""
        v = self.measure("PDUTy", ch)
        return None if v is None else (v * 100 if v <= 1 else v)

    def getRiseTime(self, ch: int = 1) -> Optional[float]:
        """10 %–90 % rise time, s."""
        return self.measure("RTIMe", ch)

    def getFallTime(self, ch: int = 1) -> Optional[float]:
        return self.measure("FTIMe", ch)

    def getPulseWidth(self, ch: int = 1, negative: bool = False) -> Optional[float]:
        """Positive (or negative) pulse width, s."""
        return self.measure("NWIDth" if negative else "PWIDth", ch)

    # ── Data ────────────────────────────────────────────────

    def getWaveform(self, ch: int = 1) -> Tuple[List[float], List[float]]:
        """The points on the screen of a channel: (times in s, volts). Uses BYTE format, then restores the
        scope's waveform format."""
        src = self._ch(ch)
        old = self.query(":WAVeform:FORMat?")
        try:
            self.write(f":WAVeform:SOURce {src}")
            self.write(":WAVeform:MODE NORMal")
            self.write(":WAVeform:FORMat BYTE")
            pre = self.query(":WAVeform:PREamble?").split(",")
            data = self.queryBlock(":WAVeform:DATA?")
        finally:
            if old and old != "BYTE":
                self.write(f":WAVeform:FORMat {old}")
        try:
            xinc, xorg, xref = float(pre[4]), float(pre[5]), float(pre[6])
            yinc, yorg, yref = float(pre[7]), float(pre[8]), float(pre[9])
        except (IndexError, ValueError):
            raise InstrumentError(f"waveform preamble not understood: {pre}")
        times = [(i - xref) * xinc + xorg for i in range(len(data))]
        volts = [(b - yorg - yref) * yinc for b in data]
        return times, volts

    def screenshot(self, path: str) -> str:
        """Save the screen as PNG; returns the path."""
        png = self.queryBlock(":DISPlay:DATA? PNG")
        if not png.startswith(b"\x89PNG"):
            raise InstrumentError("screenshot: the scope did not send a PNG")
        with open(path, "wb") as f:
            f.write(png)
        return path


if __name__ == "__main__":                             # read-only check: python3 instruments/rigol_dho.py <ip>
    import sys
    s = RigolScope(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.146")
    print(s.idn(), "- model:", s.checkModel())
    for c in (1, 2):
        print(f"CH{c}: Vpp={s.getVoltPkPk(c)}  f={s.getFrequency(c)}  Vavg={s.getVoltAvg(c)}")
    print("errors:", s.errors() or "none")
