"""Demo: full board sequence where every step passes (no hardware needed)."""
import random
import time

from testStrategy import TestStrategy

ts = TestStrategy()


def step(seconds):
    time.sleep(seconds)
    return True


def steps():
    ts.logResult("Fixture power on", step(0.3), "OK")
    ts.logResult("StLink VCC on", step(0.2), "OK")
    print("Flashing test firmware DEMO_EOLT_V1.hex ...")
    ts.logResult("Erase chip", step(1.0), "Chip erased successfully")
    ts.logResult("Flash chip", step(1.5), "Chip flashed successfully")
    ts.logResult("Verify flash", step(0.8), "Chip verified successfully")
    ts.logResult("StLink VCC off", step(0.2), "OK")
    ts.numericLimitTestInclusive("UUT response", 4, 4, 4, "")
    time.sleep(0.4)
    ts.numericLimitTest("Flowmeter pulse count", 20, 19, 21, "pulses")
    time.sleep(0.6)
    ts.numericLimitTest("NTC HI", random.randint(212, 222), 207, 227, "")
    time.sleep(0.6)
    ts.numericLimitTest("NTC LO", random.randint(130, 140), 125, 145, "")
    time.sleep(0.8)
    ts.numericLimitTest("Minus 8V", round(random.uniform(7.7, 7.9), 2), 7.3, 8.3, "V")
    time.sleep(0.8)
    ts.numericLimitTest("3.3V", round(random.uniform(3.28, 3.32), 2), 3.1, 3.5, "V")


def finalize():
    ts.logResult("StLink VCC off", step(0.1), "OK")
    ts.logResult("Fixture power off", step(0.3), "OK")


if __name__ == "__main__":
    print("Demo board test started")
    ts.run(steps, finalize)
    print("Demo board test finished")
