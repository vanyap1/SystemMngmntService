"""Load ↔ supply loop: PSU_CUSTOM6020 CH2 → Siglent SDL1020X input (max 16 V, 1 A).

CC / CR / CP modes of the load, the supply's regulation and current limit, both instruments' meters against
each other, input / output switching. Every supply setting passes psu_set(), every load setting load_set():
never above V_MAX / I_MAX — the load's CC level keeps the current down, not the supply's limit (below 1 A the
module's limit is not exact: 0.6 A flowed at a 0.4 A preset). The supply is measured only by its external sensors
(psu.getVoltage / getCurrent: the voltage and current at its terminals). The load's CV mode is not used: load CV +
supply limit oscillate (current peaks of several A).
"""
import time

from instruments.psu_custom6020 import PSU_CUSTOM6020
from instruments.siglent_sdl1020x import SIGLENT_SDL1020X
from testStrategy import TestStrategy

ts = TestStrategy()
psu = PSU_CUSTOM6020("192.168.1.91")
load = SIGLENT_SDL1020X("192.168.1.72")

CH = 2                       # supply channel wired to the load
V_MAX = 16.0                 # limits of this setup — never exceeded
I_MAX = 1.0
SETTLE = 0.8                 # s after a load change before measuring
PSU_SETTLE = 2.0             # s after a supply preset: the PSU module regulates slowly
LEADS_MAX = 0.6              # Ω, supply → load wires (long leads, no sense lines: the voltage drops under load)
supply_v = 0.0               # present supply setpoint (for the current a CR / CP setting would draw)


# ── Helpers ─────────────────────────────────────────────────

def psu_set(volts, amps, on=True):
    """The only way the supply is set in this script."""
    global supply_v
    if not (0 <= volts <= V_MAX and 0 < amps <= I_MAX):
        raise ValueError(f"supply {volts} V / {amps} A is outside {V_MAX} V / {I_MAX} A")
    psu.setup(CH, volts, amps, on)
    supply_v = volts
    if on:
        time.sleep(PSU_SETTLE)


def load_set(mode, value):
    """Change the load mode / level with the input off, then switch it on. Refuses a setting that could draw more
    than I_MAX at the present supply voltage (CP at 90 % of it), and CV (see the module docstring)."""
    draw = {"CC": lambda: value, "CR": lambda: supply_v / value, "CP": lambda: value / (0.9 * supply_v)}
    if mode not in draw or draw[mode]() > I_MAX:
        raise ValueError(f"load {mode} {value} is not allowed here (max {I_MAX} A at {supply_v} V)")
    load.off()
    load.setup(mode, value, on=True)
    time.sleep(SETTLE)


def settle(volts, tolerance=0.15, timeout=8.0):
    """After a supply / load change the module needs ~2 s: wait for three load readings in a row near ``volts``."""
    end, ok = time.time() + timeout, 0
    while time.time() < end and ok < 3:
        ok = ok + 1 if abs(load.getVoltage() - volts) <= tolerance else 0
        time.sleep(0.3)


def near(name, value, target, rel=0.02, absolute=0.02, units="V"):
    """numericLimitTest around a target: ± (rel × |target| + absolute)."""
    d = abs(target) * rel + absolute
    shown = None if value is None else round(value, 4)
    ts.numericLimitTest(name, shown, round(target - d, 4), round(target + d, 4), units)


# ── Steps ───────────────────────────────────────────────────

def steps():
    ts.section("Instruments")
    ts.logResult("Load", True, load.checkModel())
    ts.logResult("Supply ready", psu.isReady(), psu.firmwareVersion())
    load.off()
    load.setCurrentProtection(1.1, delay=0.2)   # second line of defence: input off above 1.1 A …
    load.setPowerProtection(17.0, delay=0.2)    # … or 17 W
    ts.logResult("Load protections on", all(load.protection().values()), "1.1 A / 17 W")

    ts.section("Open circuit, 12 V")
    psu_set(12.0, I_MAX)
    near("Supply 12 V", psu.waitVoltage(CH, 12.0, 0.2, 5), 12.0, rel=0.01, absolute=0.1)
    time.sleep(SETTLE)
    near("Load sees 12 V", load.getVoltage(), 12.0, rel=0.01, absolute=0.1)
    near("No current (load)", load.getCurrent(), 0.0, rel=0, absolute=0.01, units="A")
    near("No current (supply)", psu.getCurrent(CH), 0.0, rel=0, absolute=0.03, units="A")

    ts.section("Constant current")
    for amps in (0.2, 0.5, 0.8):
        load_set("CC", amps)
        v, i, p = load.measureAll()
        near(f"CC {amps} A: load current", i, amps, rel=0.01, absolute=0.01, units="A")
        near(f"CC {amps} A: supply current", psu.getCurrent(CH), i, rel=0.03, absolute=0.03, units="A")
        ts.numericLimitTest(f"CC {amps} A: voltage under load", round(v, 4), round(12.0 - 0.15 - amps * LEADS_MAX, 3),
                            12.2, "V")
        near(f"CC {amps} A: power = V × I", p, v * i, rel=0.02, absolute=0.02, units="W")

    ts.section("Constant resistance, 24 Ω")
    load_set("CR", 24.0)
    v, i, _ = load.measureAll()
    near("CR: current = V / 24 Ω", i, v / 24.0, rel=0.02, absolute=0.01, units="A")
    near("CR: measured resistance", load.getResistance(), 24.0, rel=0.03, absolute=0.2, units="Ω")

    ts.section("Constant power, 6 W")
    load_set("CP", 6.0)
    v, i, p = load.measureAll()
    near("CP: power", p, 6.0, rel=0.02, absolute=0.05, units="W")
    near("CP: current = 6 W / V", i, 6.0 / v if v else None, rel=0.02, absolute=0.01, units="A")

    ts.section("Supply voltage steps at 0.5 A")
    load_set("CC", 0.5)
    for volts in (5.0, 12.0, 16.0):
        psu_set(volts, I_MAX)
        settle(volts)
        vl, vs = load.getVoltage(), psu.getVoltage(CH)
        ts.numericLimitTest(f"{volts:g} V: at the load", round(vl, 4), round(volts * 0.99 - 0.1 - 0.5 * LEADS_MAX, 3),
                            round(volts * 1.01 + 0.1, 3), "V")
        ts.numericLimitTest(f"{volts:g} V: drop in the leads", round(vs - vl, 4), -0.05, 0.5 * LEADS_MAX + 0.05, "V")
        near(f"{volts:g} V: current", load.getCurrent(), 0.5, rel=0.01, absolute=0.01, units="A")

    ts.section("Supply sensors vs load at 0.8 A")
    psu_set(12.0, I_MAX)
    load_set("CC", 0.8)
    settle(12.0, 0.3)
    i_load = load.getCurrent()
    ts.numericLimitTest("Lead resistance (supply V − load V) / I",
                        round((psu.getVoltage(CH) - load.getVoltage()) / i_load, 3), -0.05, LEADS_MAX, "Ω")
    near("Supply current = load current", psu.getCurrent(CH), i_load, rel=0.03, absolute=0.02, units="A")

    ts.section("Load step 0.2 → 0.8 A at 12 V")
    load_set("CC", 0.2)
    settle(12.0, 0.3)
    v_light = load.getVoltage()
    load.setCC(0.8)                              # step with the input on
    time.sleep(0.2)
    ts.numericLimitTest("Dip right after the step", round(load.getVoltage(), 3), 10.5, 12.5, "V")
    settle(12.0, 0.3)
    near("Recovered at 0.8 A", load.getVoltage(), v_light, rel=0, absolute=0.25)
    load.off()

    ts.section("Switching")
    load_set("CC", 0.5)
    near("Load on: 0.5 A", load.getCurrent(), 0.5, rel=0.01, absolute=0.01, units="A")
    load.off()
    time.sleep(SETTLE)
    near("Load off: no current", load.getCurrent(), 0.0, rel=0, absolute=0.01, units="A")
    psu.off(CH)
    load_set("CC", 0.1)                          # discharge the output capacitors
    time.sleep(1.0)
    near("Supply off: no voltage", load.getVoltage(), 0.0, rel=0, absolute=0.5)
    load.off()


def finalize():
    try:
        load.off()
    finally:
        try:
            psu.off(CH)
        finally:
            try:
                load.setCurrentProtection(None)
                load.setPowerProtection(None)
                load.setCC(1.0)                  # back to the state found: CC 1 A, input off
            finally:
                load.close()


ts.run(steps, finalize)
