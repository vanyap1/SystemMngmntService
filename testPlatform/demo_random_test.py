"""Demo: random spread, tight limits — FAIL/ERROR shows stop-on-fail jumping to finalization."""
import random
import time

from testStrategy import TestStrategy

ts = TestStrategy()


def measure(nominal, spread):
    time.sleep(0.5)
    return round(random.gauss(nominal, spread), 2)


def steps():
    ts.logResult("Fixture power on", True, "OK")
    ts.numericLimitTest("Supply 12V", measure(12.0, 0.15), 11.7, 12.3, "V")
    ts.numericLimitTest("Supply 5V", measure(5.0, 0.08), 4.85, 5.15, "V")
    ts.numericLimitTest("Supply 3.3V", measure(3.3, 0.06), 3.2, 3.4, "V")
    ts.numericLimitTest("Idle current", measure(42, 4), 35, 50, "mA")
    ts.numericLimitTest("Oscillator", measure(8000, 30), 7950, 8050, "kHz")
    # A broken DMM reading shows up as ERROR (value cannot be converted)
    reading = "OL" if random.random() < 0.3 else measure(1.25, 0.01)
    ts.numericLimitTest("Reference 1.25V", reading, 1.22, 1.28, "V")
    ts.stringMatchTest("FW version", random.choice(["4", "4", "4", "3"]), "4")
    ts.booleanTest("Key1 released", True, True)


def finalize():
    ts.logResult("Discharge outputs", True, "OK")
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    print("Demo random test: limits are tight, expect occasional FAIL")
    print(f"Stop on fail: {'on' if ts.stopOnFail else 'off'}")
    ts.run(steps, finalize)
