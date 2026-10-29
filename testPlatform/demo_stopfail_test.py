"""Demo: step 3 always fails — compare runs with "Stop on fail" checked and unchecked."""
import time

from testStrategy import TestStrategy

ts = TestStrategy()


def steps():
    ts.logResult("Fixture power on", True, "OK")
    time.sleep(0.3)
    ts.numericLimitTest("Supply 12V", 12.02, 11.7, 12.3, "V")
    time.sleep(0.3)
    ts.numericLimitTest("Supply 5V", 5.61, 4.85, 5.15, "V")      # always FAIL
    time.sleep(0.3)
    ts.numericLimitTest("Supply 3.3V", 3.30, 3.2, 3.4, "V")
    time.sleep(0.3)
    ts.numericLimitTest("Idle current", 41.5, 35, 50, "mA")
    ts.logResult("Flash final FW", True, "Chip flashed successfully")


def finalize():
    ts.logResult("Discharge outputs", True, "OK")
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    ts.run(steps, finalize)
