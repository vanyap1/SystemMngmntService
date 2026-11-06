"""Demo: emergency stop pressed during the sequence — the watch aborts the test, finalization still runs."""
import time

from testStrategy import TestStrategy
from testWatch import EmergencyStop, TestWatch

ts = TestStrategy()
started = time.time()


def estop_button():
    """Simulated button: "pressed" 2 s after the start. A real one reads an input and raises the same way."""
    if time.time() - started > 2.0:
        raise EmergencyStop("button pressed")


watch = TestWatch(interval=0.05)
watch.add("Emergency stop", estop_button)


def steps():
    ts.logResult("Fixture power on", True, "OK")
    ts.numericLimitTest("Supply 12V", 12.02, 11.7, 12.3, "V")
    print("Burn-in 10 s ...")
    time.sleep(10)                       # interrupted by the emergency stop after ~2 s
    ts.logResult("Burn-in", True, "10 s")


def finalize():
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    ts.run(steps, finalize, watch=watch)
