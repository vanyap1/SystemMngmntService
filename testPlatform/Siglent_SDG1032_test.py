"""Generator ↔ scope loopback: SDG1032X CH1 → BNC cable → DHO924 CH1 (no divider, no termination).

Checks amplitude, offset, DC levels, frequency accuracy and flatness up to 10 MHz, square duty and edges, pulse
width, the 50 Ω load setting, a manual-triggered burst and the output switch. The scope is set up explicitly
(probe 1×, DC coupling, scale / timebase / trigger for each signal) — no autoset, so every run measures the same.
"""
import math
import time

from instruments.rigol_dho924 import RIGOL_DHO924
from instruments.siglent_sdg1032x import SIGLENT_SDG1032X
from testStrategy import TestStrategy

ts = TestStrategy()
gen = SIGLENT_SDG1032X("192.168.1.73")
scope = RIGOL_DHO924("192.168.1.146")

CH = 1                       # generator CH1 and scope CH1 are connected


# ── Helpers ─────────────────────────────────────────────────

def view(vpp, center=0.0, freq=None, periods=4, slope="POS"):
    """Scope CH1 framed for a signal: ``vpp`` over ~6 divisions around ``center``, ``periods`` on the screen,
    triggered at the centre level; then wait for fresh acquisitions."""
    scope.setScale(CH, max(vpp / 6, 0.005))
    scope.setOffset(CH, -center)
    if freq:
        scope.setTimebase(periods / (freq * 10))
    scope.setTimeOffset(0)
    scope.setTrigger(CH, center, slope, "AUTO")
    time.sleep(0.6)


def avg(item):
    return scope.measureAvg(item, CH, n=3, delay=0.15)


def periods_in(volts, high, low):
    """Count periods in a captured waveform: rising crossings of ``high`` after the signal was below ``low``."""
    n, armed = 0, True
    for v in volts:
        if armed and v > high:
            n, armed = n + 1, False
        elif v < low:
            armed = True
    return n


def hz(f):
    """Frequency → (text, unit, scale) for readable rows: 100 Hz, 10 kHz, 1 MHz."""
    for unit, k in (("MHz", 1e6), ("kHz", 1e3)):
        if f >= k:
            return f"{f / k:g} {unit}", unit, 1 / k
    return f"{f:g} Hz", "Hz", 1.0


def near(name, value, target, rel=0.03, absolute=0.02, units="V", scale=1.0):
    """numericLimitTest around a target: ± (rel × |target| + absolute). ``scale`` converts the shown value
    (e.g. 1e9 → ns)."""
    d = abs(target) * rel + absolute
    shown = None if value is None else round(value * scale, 4)
    ts.numericLimitTest(name, shown, round((target - d) * scale, 4), round((target + d) * scale, 4), units)


# ── Steps ───────────────────────────────────────────────────

def steps():
    ts.section("Instruments")
    ts.logResult("Generator", True, gen.checkModel())
    ts.logResult("Scope", True, scope.checkModel())
    gen.allOff()
    gen.setLoad(CH, "HZ")                       # the scope input is 1 MΩ: amplitudes = what the scope sees
    gen.invert(CH, False)
    scope.run()
    scope.setChannel(CH, True)
    scope.setProbe(CH, 1)                       # BNC cable, no probe
    scope.setCoupling(CH, "DC")
    scope.setBandwidthLimit(CH, False)

    ts.section("Sine amplitude, 1 kHz")
    for vpp in (0.5, 2.0, 5.0, 10.0):
        gen.sine(CH, 1000, vpp)
        view(vpp, 0, 1000)
        near(f"Vpp {vpp:g} V", avg("VPP"), vpp, rel=0.05, absolute=0.03)
        if vpp == 2.0:
            near("Vrms 2 Vpp", avg("VRMS"), vpp / (2 * math.sqrt(2)), rel=0.03, absolute=0.01)
            near("Vavg 2 Vpp", avg("VAVG"), 0.0, rel=0, absolute=0.03)

    ts.section("Offset and DC")
    gen.sine(CH, 1000, 2.0, offset=1.0)
    view(2.0, 1.0, 1000)
    near("Offset +1 V: max", avg("VMAX"), 2.0, rel=0.04, absolute=0.05)
    near("Offset +1 V: min", avg("VMIN"), 0.0, rel=0, absolute=0.1)
    near("Offset +1 V: avg", avg("VAVG"), 1.0, rel=0.02, absolute=0.03)
    for level in (1.5, -2.0, 4.0):
        gen.dc(CH, level)
        view(2.0, level)
        near(f"DC {level:+g} V", avg("VAVG"), level, rel=0.02, absolute=0.03)

    ts.section("Frequency accuracy and flatness, 2 Vpp sine")
    for f in (100, 1e3, 10e3, 100e3, 1e6, 10e6):
        gen.sine(CH, f, 2.0)
        view(2.0, 0, f)
        text, unit, k = hz(f)
        near(f"Frequency {text}", avg("FREQuency"), f, rel=0.002, absolute=0, units=unit, scale=k)
        near(f"Vpp at {text}", avg("VPP"), 2.0, rel=0.08 if f >= 1e6 else 0.05, absolute=0.03)

    ts.section("Square 10 kHz, 0…3.3 V")
    for duty in (50, 25, 75):
        gen.square(CH, 10e3, 3.3, offset=1.65, duty=duty)
        view(3.3, 1.65, 10e3)
        near(f"Duty {duty} %", scope.getDutyCycle(CH), duty, rel=0, absolute=1.0, units="%")
    near("High level (top)", avg("VTOP"), 3.3, rel=0.03, absolute=0.1)      # VTOP / VBASe: flat parts, without
    near("Low level (base)", avg("VBASe"), 0.0, rel=0, absolute=0.1)       # the overshoot of the open cable
    gen.square(CH, 100e3, 3.3, offset=1.65)
    view(3.3, 1.65)
    scope.setTimebase(10e-9)                    # one edge in the middle of the screen
    time.sleep(0.6)
    near("Rise time", avg("RTIMe"), 10e-9, rel=0, absolute=9e-9, units="ns", scale=1e9)
    scope.setTrigger(CH, 1.65, "NEG", "AUTO")
    time.sleep(0.6)
    near("Fall time", avg("FTIMe"), 10e-9, rel=0, absolute=9e-9, units="ns", scale=1e9)

    ts.section("Pulse 1 kHz, 0…5 V")
    for width in (100e-6, 10e-6):
        gen.pulse(CH, 1000, 5.0, width, offset=2.5)
        view(5.0, 2.5)
        scope.setTimebase(width / 2)            # the pulse over ~5 divisions
        scope.setTimeOffset(width / 2)
        time.sleep(0.6)
        near(f"Width {width * 1e6:g} µs", avg("PWIDth"), width, rel=0.02, absolute=50e-9, units="µs", scale=1e6)

    ts.section("Load setting")
    gen.setLoad(CH, 50)                         # the generator now assumes 50 Ω: into 1 MΩ it shows double
    gen.sine(CH, 1000, 1.0)
    view(2.0, 0, 1000)
    near("1 Vpp @50 Ω into HiZ", avg("VPP"), 2.0, rel=0.05, absolute=0.03)
    gen.setLoad(CH, "HZ")

    ts.section("Burst: 5 cycles, manual trigger")
    gen.sine(CH, 1000, 2.0)
    gen.burst(CH, 5, "MAN")
    view(2.0, 0)
    scope.setTimebase(1e-3)                     # 10 ms on the screen, the 5 ms burst after the trigger
    scope.setTimeOffset(4e-3)
    scope.setTrigger(CH, 0.5, "POS", "NORM")
    time.sleep(0.5)
    scope.single()
    time.sleep(0.5)
    gen.trigger(CH)
    ts.logResult("Burst captured", scope.waitTriggered(5), "single acquisition")
    _, volts = scope.getWaveform(CH)                                       # the captured screen
    ts.numericLimitTestInclusive("Periods in the burst", periods_in(volts, 0.5, -0.5), 5, 5, "")
    gen.burstOff(CH)
    scope.run()

    ts.section("Output switch")
    gen.sine(CH, 1000, 2.0)
    gen.off(CH)
    view(0.3, 0, 1000)
    near("Output off: Vpp", avg("VPP"), 0.0, rel=0, absolute=0.05)
    gen.on(CH)
    view(2.0, 0, 1000)
    near("Output on again: Vpp", avg("VPP"), 2.0, rel=0.05, absolute=0.03)


def finalize():
    try:
        gen.burstOff(CH)
        gen.allOff()
        gen.setLoad(CH, "HZ")
    finally:
        scope.setTrigger(CH, 0, "POS", "AUTO")
        scope.setTimeOffset(0)
        scope.run()
        gen.close()
        scope.close()


ts.run(steps, finalize)
