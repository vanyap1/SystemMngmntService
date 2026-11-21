"""Siglent SDS802X HD demo: identity, ripple setup (CH1, probe 1×, AC, 50 mV/div, 5 µs/div), ripple and basic
measurements, a single acquisition read as a waveform, a screenshot in testPlatform/data/.

Only the scope is used — whatever is connected to CH1 is measured (no limits on the signal: the demo shows the
calls, the limits are wide). The trigger mode found at the start is restored in finalize().
"""
import os
import time

from instruments.param_file import data_path
from instruments.siglent_sds802xhd import SIGLENT_SDS802XHD
from testStrategy import TestStrategy

ts = TestStrategy()
scope = SIGLENT_SDS802XHD("192.168.1.75")

CH = 1
state = {}


def steps():
    ts.section("Scope")
    ts.logResult("Model", True, scope.checkModel())
    state["mode"] = scope.getTriggerMode()
    ts.logResult("Errors before", not scope.errors(), "queue empty")

    ts.section("Ripple setup")
    scope.setupRipple(CH)                                    # probe 1×, AC, 50 mV/div, 5 µs/div, 20 MHz, AUTO
    ts.stringMatchTest("Coupling", scope.getCoupling(CH), "AC")
    ts.numericLimitTestInclusive("Probe", scope.getProbe(CH), 1, 1, "x")
    ts.numericLimitTestInclusive("Scale", round(scope.getScale(CH) * 1000, 3), 50, 50, "mV/div")
    ts.numericLimitTestInclusive("Timebase", round(scope.getTimebase() * 1e6, 3), 5, 5, "µs/div")

    ts.section("Measurements")
    ripple = scope.getRipple(CH, n=10)
    ts.numericLimitTest("Ripple (worst of 10)", None if ripple is None else round(ripple * 1000, 2), 0, 400, "mV")
    st = scope.measureStats("PKPK", CH, n=5)
    ts.logResult("PKPK min / mean / max", st is not None,
                 "no value" if st is None else " / ".join(f"{v * 1000:.2f}" for v in st) + " mV")
    rms = scope.getVoltRms(CH)
    ts.logResult("RMS", rms is not None, "no value" if rms is None else f"{rms * 1000:.2f} mV")
    f = scope.getFrequency(CH)
    ts.logResult("Frequency", True, "no periodic signal" if f is None else f"{f:.1f} Hz")
    ts.numericLimitTestInclusive("Sample rate", scope.getSampleRate() / 1e6, 1, 2000, "MSa/s")

    ts.section("Single acquisition")
    scope.single()
    ts.logResult("Acquired", scope.waitTriggered(5), scope.triggerStatus())
    times, volts = scope.getWaveform(CH, points=2000)
    ts.numericLimitTest("Waveform points", len(volts), 1000, 3000, "")
    ts.numericLimitTest("Waveform span", round((times[-1] - times[0]) * 1e6, 2), 45, 55, "µs")
    ts.numericLimitTest("Waveform pk-pk", round((max(volts) - min(volts)) * 1000, 2), 0, 400, "mV")
    path = scope.screenshot(data_path(f"sds802xhd_{time.strftime('%Y%m%d_%H%M%S')}.png"))
    ts.logResult("Screenshot", True, os.path.basename(path))
    ts.logResult("Errors after", not scope.errors(), "queue empty")


def finalize():
    try:
        scope.setTriggerMode(state.get("mode", "AUTO"))
        scope.run()
    finally:
        scope.close()


ts.run(steps, finalize)
