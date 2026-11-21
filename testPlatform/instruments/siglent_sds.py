"""Siglent SDS800X HD oscilloscopes (SDS802X HD, SDS804X HD, SDS814X HD …) over LAN (raw SCPI socket :5025) —
common driver. Scripts use the model class: instruments/siglent_sds802xhd.py → SIGLENT_SDS802XHD.

    from instruments.siglent_sds802xhd import SIGLENT_SDS802XHD

    scope = SIGLENT_SDS802XHD("192.168.1.75")    # host, port=5025, timeout=5.0
    scope.setupRipple(1)                         # CH1: probe 1×, AC, 50 mV/div, 5 µs/div, 20 MHz limit, trigger AUTO
    ripple = scope.getRipple(1)                  # worst peak-to-peak of 10 readings, V
    f = scope.getFrequency(1)                    # Hz, None when the scope cannot measure

Channels are 1…4 (the 2-channel models: 1, 2). Measurements use the scope's simple measurement (switched on by the
first measurement) and return float or None ("****" = cannot measure) — numericLimitTest turns None into an ERROR
row. The scope never answers a setting command: errors() / checkErrors() read its error queue.
Command reference: Siglent "SDS800X HD / SDS1000X HD / SDS2000X HD Programming Guide".
"""
import struct
import time
from typing import List, Optional, Tuple

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.scpi import InstrumentError, ScpiInstrument  # noqa: E402

MEAS_ITEMS = ("PKPK", "MAX", "MIN", "AMPL", "TOP", "BASE", "LEVELX", "CMEAN", "MEAN", "STDEV", "VSTD", "RMS",
              "CRMS", "OVSN", "FPRE", "OVSP", "RPRE", "PER", "FREQ", "TMAX", "TMIN", "PWID", "NWID", "DUTY",
              "NDUTY", "WID", "NBWID", "DELAY", "TIMEL", "RISE", "FALL", "RISE20T80", "FALL80T20", "CCJ", "PPULSE",
              "NPULSE", "PEDGE", "NEDGE")
_PNG_END = b"IEND\xaeB`\x82"


class SiglentSDS(ScpiInstrument):
    """Common driver of the SDS800X HD series; MODEL / CHANNELS come from the model class."""
    DEFAULT_PORT = 5025
    CHANNELS = 4
    SETTLE = 0.3                         # s for the measurements to follow a changed setting / source

    def __init__(self, host: str = "192.168.1.75", port: int = DEFAULT_PORT, timeout: float = 5.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)
        self._meas_src: Optional[str] = None

    def _ch(self, ch) -> str:
        if ch not in range(1, self.CHANNELS + 1):
            raise ValueError(f"channel must be 1…{self.CHANNELS}")
        return f"CHANnel{ch}"

    def checkErrors(self) -> None:
        """Raise InstrumentError if the scope's error queue is not empty (call it after a group of settings)."""
        errs = self.errors()
        if errs:
            raise InstrumentError("; ".join(errs))

    def _number(self, cmd: str) -> float:
        v = self.queryFloat(cmd)
        if v is None:
            raise InstrumentError(f"{cmd}: no value")
        return v

    # ── Acquisition ─────────────────────────────────────────

    def autoset(self, wait: float = 4.0) -> None:
        """AUTO setup: find the signals and set scale, timebase and trigger (takes a few seconds)."""
        self.write(":AUToset")
        time.sleep(wait)

    def run(self) -> None:
        """Acquire continuously (the trigger mode set before: AUTO / NORMal)."""
        self.write(":TRIGger:RUN")

    def stop(self) -> None:
        self.write(":TRIGger:STOP")

    def single(self) -> None:
        """Arm one acquisition (trigger mode SINGle); waitTriggered() waits for it."""
        self.write(":TRIGger:MODE SINGle")

    def setTriggerMode(self, mode: str = "AUTO") -> None:
        """AUTO (acquires without a trigger too), NORMal or SINGle."""
        mode = {"AUTO": "AUTO", "NORM": "NORMal", "NORMAL": "NORMal", "SING": "SINGle", "SINGLE": "SINGle"}.get(
            mode.upper())
        if not mode:
            raise ValueError("trigger mode: AUTO, NORMal or SINGle")
        self.write(f":TRIGger:MODE {mode}")

    def getTriggerMode(self) -> str:
        """"AUTO", "NORMal" or "SINGle"."""
        return self.query(":TRIGger:MODE?")

    def triggerStatus(self) -> str:
        """"Arm", "Ready", "Auto", "Trig'd", "Stop" or "Roll"."""
        return self.query(":TRIGger:STATus?")

    def waitTriggered(self, timeout: float = 5.0) -> bool:
        """After single(): wait until the acquisition is complete (status Stop); False on timeout."""
        end = time.time() + timeout
        time.sleep(0.1)
        while time.time() < end:
            if self.triggerStatus().upper() == "STOP":
                return True
            time.sleep(0.05)
        return False

    def getSampleRate(self) -> float:
        """Current sample rate, Sa/s."""
        return self._number(":ACQuire:SRATe?")

    # ── Vertical ────────────────────────────────────────────

    def setChannel(self, ch: int, on: bool = True) -> None:
        """Show / hide a channel."""
        self.write(f":{self._ch(ch)}:SWITch {'ON' if on else 'OFF'}")

    def isChannelOn(self, ch: int) -> bool:
        return self.query(f":{self._ch(ch)}:SWITch?").upper() == "ON"

    def setScale(self, ch: int, volts_per_div: float) -> None:
        """Vertical scale, V/div (at the probe tip: the probe ratio is included)."""
        self.write(f":{self._ch(ch)}:SCALe {float(volts_per_div):.6g}")

    def getScale(self, ch: int) -> float:
        return self._number(f":{self._ch(ch)}:SCALe?")

    def setOffset(self, ch: int, volts: float) -> None:
        self.write(f":{self._ch(ch)}:OFFSet {float(volts):.6g}")

    def getOffset(self, ch: int) -> float:
        return self._number(f":{self._ch(ch)}:OFFSet?")

    def setCoupling(self, ch: int, coupling: str = "DC") -> None:
        """DC, AC or GND."""
        coupling = coupling.upper()
        if coupling not in ("DC", "AC", "GND"):
            raise ValueError("coupling: DC, AC or GND")
        self.write(f":{self._ch(ch)}:COUPling {coupling}")

    def getCoupling(self, ch: int) -> str:
        return self.query(f":{self._ch(ch)}:COUPling?").upper()

    def setProbe(self, ch: int, ratio: float = 10) -> None:
        """Probe attenuation (1, 10, 100 …)."""
        self.write(f":{self._ch(ch)}:PROBe VALue,{float(ratio):.6g}")

    def getProbe(self, ch: int) -> float:
        return self._number(f":{self._ch(ch)}:PROBe?")

    def setBandwidthLimit(self, ch: int, on: bool = True) -> None:
        """20 MHz bandwidth limit on / off (on for ripple: cuts the RF pick-up of the probe)."""
        self.write(f":{self._ch(ch)}:BWLimit {'20M' if on else 'FULL'}")

    # ── Horizontal ──────────────────────────────────────────

    def setTimebase(self, seconds_per_div: float) -> None:
        self.write(f":TIMebase:SCALe {float(seconds_per_div):.6g}")

    def getTimebase(self) -> float:
        return self._number(":TIMebase:SCALe?")

    def setTimeOffset(self, seconds: float) -> None:
        """Trigger delay (horizontal position), s."""
        self.write(f":TIMebase:DELay {float(seconds):.6g}")

    def getTimeOffset(self) -> float:
        return self._number(":TIMebase:DELay?")

    # ── Trigger ─────────────────────────────────────────────

    def setTrigger(self, ch: int = 1, level: float = 0.0, slope: str = "RISing", mode: str = "AUTO") -> None:
        """Edge trigger on a channel: level in V, slope RISing / FALLing / ALTernate, mode AUTO / NORMal / SINGle."""
        slopes = {"RIS": "RISing", "RISING": "RISing", "POS": "RISing", "FALL": "FALLing", "FALLING": "FALLing",
                  "NEG": "FALLing", "ALT": "ALTernate", "ALTERNATE": "ALTernate"}
        sl = slopes.get(slope.upper())
        if not sl:
            raise ValueError("slope: RISing, FALLing or ALTernate")
        self._ch(ch)
        self.write(":TRIGger:TYPE EDGE")
        self.write(f":TRIGger:EDGE:SOURce C{ch}")
        self.write(f":TRIGger:EDGE:SLOPe {sl}")
        self.write(f":TRIGger:EDGE:LEVel {float(level):.6g}")
        self.setTriggerMode(mode)

    def setTriggerLevel(self, level: float) -> None:
        self.write(f":TRIGger:EDGE:LEVel {float(level):.6g}")

    # ── Measurements ────────────────────────────────────────

    def measure(self, item: str, ch: int = 1) -> Optional[float]:
        """Any simple measurement item of the scope (PKPK, FREQ, RISE … see MEAS_ITEMS); None = cannot measure."""
        src = f"C{ch}"
        self._ch(ch)
        if self._meas_src != src:
            self.write(":MEASure ON")
            self.write(":MEASure:MODE SIMPle")
            self.write(f":MEASure:SIMPle:SOURce {src}")
            self._meas_src = src
            time.sleep(self.SETTLE)
        answer = self.query(f":MEASure:SIMPle:VALue? {item}")
        if "zero" in answer.lower():                       # "The number of measurements is zero": switched off
            self.write(":MEASure ON")
            time.sleep(self.SETTLE)
            answer = self.query(f":MEASure:SIMPle:VALue? {item}")
        try:
            v = float(answer)
        except ValueError:
            if not answer.strip("*") or "zero" in answer.lower():
                return None
            raise InstrumentError(f"measure {item}: unexpected answer {answer!r}")
        return None if abs(v) >= self.INVALID else v

    def measureStats(self, item: str, ch: int = 1, n: int = 10,
                     delay: float = 0.2) -> Optional[Tuple[float, float, float]]:
        """(min, mean, max) of n readings (None values skipped; None if all were invalid)."""
        vals = []
        for i in range(n):
            if i:
                time.sleep(delay)
            v = self.measure(item, ch)
            if v is not None:
                vals.append(v)
        return (min(vals), sum(vals) / len(vals), max(vals)) if vals else None

    def measureAvg(self, item: str, ch: int = 1, n: int = 5, delay: float = 0.2) -> Optional[float]:
        """Mean of n readings (None if all were invalid)."""
        st = self.measureStats(item, ch, n, delay)
        return None if st is None else st[1]

    def getVoltPkPk(self, ch: int = 1) -> Optional[float]:
        """Peak-to-peak voltage, V."""
        return self.measure("PKPK", ch)

    def getVoltMax(self, ch: int = 1) -> Optional[float]:
        return self.measure("MAX", ch)

    def getVoltMin(self, ch: int = 1) -> Optional[float]:
        return self.measure("MIN", ch)

    def getVoltAmplitude(self, ch: int = 1) -> Optional[float]:
        """Top − base, V."""
        return self.measure("AMPL", ch)

    def getVoltAvg(self, ch: int = 1) -> Optional[float]:
        return self.measure("MEAN", ch)

    def getVoltRms(self, ch: int = 1) -> Optional[float]:
        return self.measure("RMS", ch)

    def getFrequency(self, ch: int = 1) -> Optional[float]:
        """Hz."""
        return self.measure("FREQ", ch)

    def getPeriod(self, ch: int = 1) -> Optional[float]:
        """s."""
        return self.measure("PER", ch)

    def getDutyCycle(self, ch: int = 1) -> Optional[float]:
        """Positive duty cycle, % (0…100)."""
        return self.measure("DUTY", ch)

    def getRiseTime(self, ch: int = 1) -> Optional[float]:
        """10 %–90 % rise time, s."""
        return self.measure("RISE", ch)

    def getFallTime(self, ch: int = 1) -> Optional[float]:
        return self.measure("FALL", ch)

    def getPulseWidth(self, ch: int = 1, negative: bool = False) -> Optional[float]:
        """Positive (or negative) pulse width, s."""
        return self.measure("NWID" if negative else "PWID", ch)

    # ── Ripple ──────────────────────────────────────────────

    def setupRipple(self, ch: int = 1, volts_per_div: float = 0.05, seconds_per_div: float = 5e-6,
                    bw_limit: bool = True, probe: Optional[float] = 1) -> None:
        """Channel set up for output ripple: probe 1× (None keeps the scope's setting), on, AC coupling, ``volts_per_div`` (50 mV), offset 0,
        ``seconds_per_div`` (5 µs), 20 MHz limit, trigger AUTO (fresh acquisitions without a trigger), running.
        Scale, coupling and timebase are read back (InstrumentError if the scope did not take them)."""
        if probe is not None:
            self.setProbe(ch, probe)
        self.setChannel(ch, True)
        self.setCoupling(ch, "AC")
        self.setScale(ch, volts_per_div)
        self.setOffset(ch, 0)
        self.setBandwidthLimit(ch, bw_limit)
        self.setTimebase(seconds_per_div)
        self.setTimeOffset(0)
        self.setTriggerMode("AUTO")
        self.run()
        got = (self.getCoupling(ch), self.getScale(ch), self.getTimebase())
        if (probe is not None and abs(self.getProbe(ch) - probe) > 1e-3) or (got[0] != "AC" or abs(got[1] - volts_per_div) > volts_per_div * 0.01
                or abs(got[2] - seconds_per_div) > seconds_per_div * 0.01):
            raise InstrumentError(f"ripple setup CH{ch}: the scope shows {got[0]}, {got[1]:g} V/div, {got[2]:g} s/div, "
                                  f"probe {self.getProbe(ch):g}x")
        time.sleep(self.SETTLE)

    def getRipple(self, ch: int = 1, n: int = 10, delay: float = 0.2) -> Optional[float]:
        """Ripple = the worst peak-to-peak voltage of n readings, V (None if the scope could not measure)."""
        st = self.measureStats("PKPK", ch, n, delay)
        return None if st is None else st[2]

    # ── Data ────────────────────────────────────────────────

    def getWaveform(self, ch: int = 1, points: int = 10000) -> Tuple[List[float], List[float]]:
        """The last acquisition of a channel, decimated to about ``points`` points: (times in s, volts).
        Stop the scope first (stop() or single() + waitTriggered()) so the data and the preamble belong together."""
        self._ch(ch)
        self.write(f":WAVeform:SOURce C{ch}")
        self.write(":WAVeform:WIDTh WORD")
        pre = self.queryBlock(":WAVeform:PREamble?")
        if len(pre) < 332 or not pre.startswith(b"WAVEDESC"):
            raise InstrumentError(f"waveform preamble not understood ({len(pre)} bytes)")
        total = struct.unpack_from("<i", pre, 116)[0]
        vdiv, voff, code_div = struct.unpack_from("<fff", pre, 156)
        dt = struct.unpack_from("<f", pre, 176)[0]
        t0 = struct.unpack_from("<d", pre, 180)[0]
        probe = struct.unpack_from("<f", pre, 328)[0] or 1.0
        step = max(1, total // max(1, points))
        count = (total + step - 1) // step
        self.write(f":WAVeform:INTerval {step}")
        self.write(":WAVeform:STARt 0")
        self.write(f":WAVeform:POINt {count}")
        raw = self.queryBlock(":WAVeform:DATA?")
        codes = struct.unpack(f"<{len(raw) // 2}h", raw[:len(raw) // 2 * 2])
        gain = vdiv * probe / code_div
        volts = [c * gain - voff * probe for c in codes]
        times = [-t0 - dt * total / 2 + i * step * dt for i in range(len(codes))]
        return times, volts

    def screenshot(self, path: str) -> str:
        """Save the screen as PNG; returns the path."""
        def go():
            self.link.write(b":PRINt? PNG" + self.TERM.encode())
            head = self.link.read_exact(8)
            if not head.startswith(b"\x89PNG"):
                raise InstrumentError("screenshot: the scope did not send a PNG")
            while _PNG_END not in self.link._buf:            # a raw PNG, not a binary block: read to IEND
                self.link._recv()
            png, _, self.link._buf = self.link._buf.partition(_PNG_END)
            return head + png + _PNG_END
        with self._lock:
            png = self._exchange(go, ":PRINt? PNG")
            time.sleep(0.2)
            self.link.drain()                                # a line end after the image, if any
        with open(path, "wb") as f:
            f.write(png)
        return path


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_sds.py <ip>
    import sys
    s = SiglentSDS(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.75")
    print(s.idn(), "- model:", s.checkModel())
    for c in (1, 2):
        print(f"CH{c}: {'on' if s.isChannelOn(c) else 'off'} {s.getCoupling(c)} {s.getScale(c):g} V/div")
    print("timebase:", s.getTimebase(), "s/div  trigger:", s.getTriggerMode(), s.triggerStatus())
    print("errors:", s.errors() or "none")
