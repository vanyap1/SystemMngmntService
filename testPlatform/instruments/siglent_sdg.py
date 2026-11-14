"""Siglent SDG function / arbitrary waveform generators (SDG1000X, SDG2000X, SDG6000X) over LAN — common driver.
Scripts use the model class: instruments/siglent_sdg1032x.py → SIGLENT_SDG1032X.

    from instruments.siglent_sdg1032x import SIGLENT_SDG1032X

    gen = SIGLENT_SDG1032X("192.168.1.73")         # host, port=5025 (raw SCPI socket), timeout=3.0
    gen.setLoad(1, 50)                             # output load: 50 Ω or "HZ" (high impedance) — sets the amplitude scale
    gen.sine(1, 1000, 2.0)                         # CH1: sine 1 kHz, 2 Vpp, output on
    gen.square(2, 10e3, 3.3, offset=1.65, duty=25) # CH2: 0…3.3 V square, 25 % duty
    gen.off(1)

Channels are 1 and 2; frequency Hz, amplitude Vpp, offset V, phase °, times s, duty / symmetry %.
Siglent specifics handled here: a setting command gets no answer and a value the generator cannot do is silently
limited (amplitude for the load, frequency for the waveform) — every set* function reads the value back and raises
InstrumentError when the generator does not have what was asked. An unknown query gets no answer at all
(InstrumentError after the timeout, the reason is in errors()).
Command reference: Siglent "SDG Series Programming Guide" (BSWV, OUTP, BTWV, SWWV, MDWV, ARWV).
"""
import re
from typing import Dict, List, Optional, Union

if __package__ in (None, ""):                            # run as a script: python3 instruments/<driver>.py
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instruments.scpi import InstrumentError, ScpiInstrument  # noqa: E402

WAVES = ("SINE", "SQUARE", "RAMP", "PULSE", "NOISE", "ARB", "DC", "PRBS", "IQ")
_NUM = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([A-Za-z%]*)$")


def parse_params(text: str) -> Dict[str, Union[float, str]]:
    """'C1:BSWV WVTP,SINE,FRQ,1000HZ,AMP,4V' → {'WVTP': 'SINE', 'FRQ': 1000.0, 'AMP': 4.0} (units dropped)."""
    body = text.split(" ", 1)[1] if " " in text else ""
    items = [x.strip() for x in body.split(",")]
    out = {}
    for k, v in zip(items[0::2], items[1::2]):
        m = _NUM.match(v)
        out[k] = float(m.group(1)) if m else v
    return out


class SiglentSDG(ScpiInstrument):
    """Common driver of the SDG series; MODEL / CHANNELS / F_MAX come from the model class."""
    DEFAULT_PORT = 5025
    WRITE_DELAY = 0.05
    CHANNELS = 2
    F_MAX = 30e6

    def __init__(self, host: str = "192.168.1.73", port: int = DEFAULT_PORT, timeout: float = 3.0) -> None:
        super().__init__(host=host, port=port, timeout=timeout)

    def _c(self, ch: int) -> str:
        if ch not in range(1, self.CHANNELS + 1):
            raise ValueError(f"channel 1..{self.CHANNELS}")
        return f"C{ch}"

    def _params(self, ch: int, what: str) -> Dict[str, Union[float, str]]:
        return parse_params(self.query(f"{self._c(ch)}:{what}?"))

    # ── Basic wave ──────────────────────────────────────────

    def getBasic(self, ch: int) -> Dict[str, Union[float, str]]:
        """All basic wave parameters: {WVTP, FRQ, PERI, AMP, AMPVRMS, OFST, HLEV, LLEV, PHSE, DUTY …}."""
        return self._params(ch, "BSWV")

    def setParam(self, ch: int, key: str, value) -> None:
        """Set one BSWV parameter (FRQ, AMP, OFST, PHSE, DUTY, SYM, WIDTH, RISE, FALL, DLY, HLEV, LLEV, STDEV,
        MEAN …) and check it was taken; numbers are compared after the generator's rounding."""
        key = key.upper()
        text = value.upper() if isinstance(value, str) else f"{float(value):.10g}"
        for _ in (1, 2):
            self.write(f"{self._c(ch)}:BSWV {key},{text}")
            got = self.getBasic(ch).get(key)
            if isinstance(value, str):
                if str(got).upper() == text:
                    return
            elif isinstance(got, float) and abs(got - float(value)) <= max(abs(float(value)) * 1e-4, 1e-3):
                return
        raise InstrumentError(f"CH{ch} {key}: {text} asked, the generator has {got!r} "
                              f"(out of range for this waveform / load?)")

    def setWaveform(self, ch: int, wave: str) -> None:
        """SINE, SQUARE, RAMP, PULSE, NOISE, ARB, DC, PRBS, IQ."""
        wave = wave.upper()
        if wave not in WAVES:
            raise ValueError(f"waveform: one of {', '.join(WAVES)}")
        self.setParam(ch, "WVTP", wave)

    def setFrequency(self, ch: int, hz: float) -> None:
        if not 0 < float(hz) <= self.F_MAX:
            raise ValueError(f"frequency 0..{self.F_MAX:g} Hz")
        self.setParam(ch, "FRQ", hz)

    def setAmplitude(self, ch: int, vpp: float) -> None:
        """Amplitude, Vpp (the range depends on the load: setLoad())."""
        self.setParam(ch, "AMP", vpp)

    def setOffset(self, ch: int, volts: float) -> None:
        self.setParam(ch, "OFST", volts)

    def setPhase(self, ch: int, degrees: float) -> None:
        self.setParam(ch, "PHSE", degrees)

    def setDuty(self, ch: int, percent: float) -> None:
        """Duty cycle of SQUARE / PULSE, %."""
        self.setParam(ch, "DUTY", percent)

    def setLevels(self, ch: int, low: float, high: float) -> None:
        """Low / high level instead of amplitude + offset, V."""
        self.setParam(ch, "HLEV", high)
        self.setParam(ch, "LLEV", low)

    def getWaveform(self, ch: int) -> str:
        return str(self.getBasic(ch).get("WVTP"))

    def getFrequency(self, ch: int) -> Optional[float]:
        return self._num(self.getBasic(ch).get("FRQ"))

    def getAmplitude(self, ch: int) -> Optional[float]:
        return self._num(self.getBasic(ch).get("AMP"))

    def getOffset(self, ch: int) -> Optional[float]:
        return self._num(self.getBasic(ch).get("OFST"))

    @staticmethod
    def _num(v) -> Optional[float]:
        return v if isinstance(v, float) else None

    # ── One-line setups ─────────────────────────────────────

    def setup(self, ch: int, wave: str, hz: Optional[float], vpp: Optional[float], offset: float = 0.0,
              on: bool = True) -> None:
        """Waveform + frequency + amplitude + offset (+ output on) in one call."""
        self.setWaveform(ch, wave)
        if hz is not None:
            self.setFrequency(ch, hz)
        if vpp is not None:
            self.setAmplitude(ch, vpp)
        self.setOffset(ch, offset)
        if on:
            self.on(ch)

    def sine(self, ch: int, hz: float, vpp: float, offset: float = 0.0, on: bool = True) -> None:
        self.setup(ch, "SINE", hz, vpp, offset, on)

    def square(self, ch: int, hz: float, vpp: float, offset: float = 0.0, duty: float = 50.0, on: bool = True) -> None:
        self.setup(ch, "SQUARE", hz, vpp, offset, on=False)
        self.setDuty(ch, duty)
        if on:
            self.on(ch)

    def ramp(self, ch: int, hz: float, vpp: float, offset: float = 0.0, symmetry: float = 50.0,
             on: bool = True) -> None:
        """Ramp / triangle (symmetry 50 %), saw (0 or 100 %)."""
        self.setup(ch, "RAMP", hz, vpp, offset, on=False)
        self.setParam(ch, "SYM", symmetry)
        if on:
            self.on(ch)

    def pulse(self, ch: int, hz: float, vpp: float, width: float, offset: float = 0.0, on: bool = True) -> None:
        """Pulse with a width in s (edges: setParam(ch, "RISE", s) / "FALL")."""
        self.setup(ch, "PULSE", hz, vpp, offset, on=False)
        self.setParam(ch, "WIDTH", width)
        if on:
            self.on(ch)

    def dc(self, ch: int, volts: float, on: bool = True) -> None:
        """Constant voltage (DC waveform, the level is the offset)."""
        self.setup(ch, "DC", None, None, volts, on)

    def noise(self, ch: int, stdev: float, mean: float = 0.0, on: bool = True) -> None:
        """Gaussian noise: standard deviation and mean, V."""
        self.setWaveform(ch, "NOISE")
        self.setParam(ch, "STDEV", stdev)
        self.setParam(ch, "MEAN", mean)
        if on:
            self.on(ch)

    def arb(self, ch: int, name: str, hz: Optional[float] = None, vpp: Optional[float] = None,
            offset: float = 0.0, on: bool = True) -> None:
        """Built-in / stored arbitrary wave by name (see arbList()), e.g. "StairUp", "Cardiac"."""
        self.write(f"{self._c(ch)}:ARWV NAME,{name}")
        got = self._params(ch, "ARWV").get("NAME")
        if str(got).lower() != name.lower():
            raise InstrumentError(f"CH{ch}: arbitrary wave {name!r} not found (has {got!r})")
        self.setup(ch, "ARB", hz, vpp, offset, on)

    def arbList(self) -> Dict[str, str]:
        """Built-in arbitrary waves: {"M2": "StairUp", …}."""
        items = [x.strip() for x in self.query("STL?").split(" ", 1)[-1].split(",")]
        return dict(zip(items[0::2], items[1::2]))

    # ── Output ──────────────────────────────────────────────

    def on(self, ch: int) -> None:
        self._output(ch, True)

    def off(self, ch: int) -> None:
        self._output(ch, False)

    def setOutput(self, ch: int, enabled: bool) -> None:
        self._output(ch, bool(enabled))

    def allOff(self) -> None:
        for ch in range(1, self.CHANNELS + 1):
            self.off(ch)

    def _output(self, ch: int, enabled: bool) -> None:
        for _ in (1, 2):
            self.write(f"{self._c(ch)}:OUTP {'ON' if enabled else 'OFF'}")
            if self.isOn(ch) == enabled:
                return
        raise InstrumentError(f"CH{ch} output did not switch {'on' if enabled else 'off'}")

    def outputState(self, ch: int) -> Dict[str, object]:
        """{"on": bool, "load": 50.0 or "HZ", "polarity": "NOR" / "INVT"}."""
        text = self.query(f"{self._c(ch)}:OUTP?")
        body = text.split(" ", 1)[-1].split(",")
        p = parse_params(text.split(" ", 1)[0] + " " + ",".join(body[1:]))
        return {"on": body[0].strip().upper() == "ON", "load": p.get("LOAD"), "polarity": p.get("PLRT")}

    def isOn(self, ch: int) -> bool:
        return self.outputState(ch)["on"]

    def setLoad(self, ch: int, load: Union[int, str]) -> None:
        """Load the output drives: ohms (50 …) or "HZ" (high impedance). Amplitudes refer to this load."""
        text = "HZ" if str(load).upper() in ("HZ", "HIGHZ", "INF") else str(int(load))
        self.write(f"{self._c(ch)}:OUTP LOAD,{text}")
        got = self.outputState(ch)["load"]
        ok = str(got).upper() == "HZ" if text == "HZ" else isinstance(got, float) and got == float(text)
        if not ok:
            raise InstrumentError(f"CH{ch} load {text}: the generator has {got!r}")

    def invert(self, ch: int, enabled: bool) -> None:
        """Inverted output polarity."""
        self.write(f"{self._c(ch)}:OUTP PLRT,{'INVT' if enabled else 'NOR'}")

    # ── Burst / sweep / modulation ──────────────────────────

    def burst(self, ch: int, cycles: int, trigger: str = "MAN", period: Optional[float] = None) -> None:
        """N-cycle burst; trigger MAN (fire with trigger()), INT (every ``period`` s) or EXT."""
        cmd = f"{self._c(ch)}:BTWV STATE,ON,GATE_NCYC,NCYC,TIME,{int(cycles)},TRSR,{trigger.upper()}"
        if period is not None:
            cmd += f",PRD,{float(period):.10g}"
        self.write(cmd)
        if self._params(ch, "BTWV").get("STATE") != "ON":
            raise InstrumentError(f"CH{ch}: burst not accepted")

    def trigger(self, ch: int) -> None:
        """Fire one burst / sweep (manual trigger)."""
        self.write(f"{self._c(ch)}:BTWV MTRIG")

    def burstOff(self, ch: int) -> None:
        self.write(f"{self._c(ch)}:BTWV STATE,OFF")

    def sweep(self, ch: int, start: float, stop: float, seconds: float, mode: str = "LINE",
              trigger: str = "INT") -> None:
        """Frequency sweep start → stop Hz in ``seconds``; mode LINE / LOG."""
        self.write(f"{self._c(ch)}:SWWV STATE,ON,TIME,{float(seconds):.10g},START,{float(start):.10g},"
                   f"STOP,{float(stop):.10g},SWMD,{mode.upper()},TRSR,{trigger.upper()}")
        if self._params(ch, "SWWV").get("STATE") != "ON":
            raise InstrumentError(f"CH{ch}: sweep not accepted")

    def sweepOff(self, ch: int) -> None:
        self.write(f"{self._c(ch)}:SWWV STATE,OFF")

    def modulate(self, ch: int, kind: str, **params) -> None:
        """Modulation AM / FM / PM / FSK / ASK / PWM / DSBAM with its parameters as in the programming guide,
        e.g. modulate(1, "AM", SRC="INT", MDSP="SINE", FRQ=100, DEPTH=50)."""
        cmd = f"{self._c(ch)}:MDWV {kind.upper()}"
        for k, v in params.items():
            cmd += f",{k.upper()},{v if isinstance(v, str) else f'{float(v):.10g}'}"
        self.write(f"{self._c(ch)}:MDWV STATE,ON")
        self.write(cmd)

    def modulationOff(self, ch: int) -> None:
        self.write(f"{self._c(ch)}:MDWV STATE,OFF")

    def getMode(self, ch: int) -> str:
        """What is on top of the basic wave: "BURST", "SWEEP", "MOD" or "" (none)."""
        for what, name in (("BTWV", "BURST"), ("SWWV", "SWEEP"), ("MDWV", "MOD")):
            if self._params(ch, what).get("STATE") == "ON":
                return name
        return ""


if __name__ == "__main__":                             # read-only check: python3 instruments/siglent_sdg.py [ip]
    import sys
    g = SiglentSDG(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.73")
    print(g.idn())
    for c in (1, 2):
        print(f"CH{c}:", g.outputState(c), g.getBasic(c), "mode:", g.getMode(c) or "basic")
    print("errors:", g.errors() or "none")
