"""Demo: long burn-in (~60 s) — press Stop: the finalization (power off) still runs."""
import random
import time

from testStrategy import TestStrategy

ts = TestStrategy()


def steps():
    ts.logResult("Burn-in chamber on", True, "OK")
    print("Burn-in: 30 temperature samples, 2 s apart")
    for i in range(1, 31):
        time.sleep(2)
        ts.numericLimitTest(f"Burn-in temperature #{i:02d}", round(random.uniform(38, 46), 1), 30, 50, "°C")
    ts.logResult("Burn-in complete", True, "OK")


def finalize():
    ts.logResult("Burn-in chamber off", True, "OK")
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    ts.run(steps, finalize)
