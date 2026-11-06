"""Demo: full board sequence where every step passes (uses the bench PSU at 192.168.1.91)."""

import os
import random
import time
from instruments.psu import PSU
 
psu = PSU("192.168.1.91")
from testStrategy import TestStrategy
from testWatch import TestWatch, file_flag

ts = TestStrategy()

# Emergency stop watched in the background during the whole sequence. Without hardware the "button" is the
# file testPlatform/ESTOP: `touch ESTOP` while the test runs = pressed (the test is aborted, finalize runs),
# `rm ESTOP` = released. With a real button replace file_flag(...) by a function that reads the input and raises
# testWatch.EmergencyStop, e.g. via gpiod:  if line.get_value(): raise EmergencyStop("button pressed")
ESTOP_FLAG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ESTOP")
watch = TestWatch(interval=0.5)
watch.add("Emergency stop", file_flag(ESTOP_FLAG, "button pressed"))


def step(seconds):
    time.sleep(seconds)
    return True


def steps():
    psu.ioOut(1, 9, 1)
    idn = psu.identify().split("\n")[1]
    ts.logResult("Serial number", True, ts.serial or "not given")    # the Serial field of the Tests page (--sn)
    ts.logResult("PSU info", True, idn)
    ts.logResult("Fixture power on", step(0.3), "OK")
    ts.logResult("StLink VCC on", step(0.2), "OK")
    print("Flashing test firmware DEMO_EOLT_V1.hex ...")
    ts.logResult("Erase chip", step(1.0), "Chip erased successfully")
    ts.logResult("Flash chip", step(1.5), "Chip flashed successfully")
    ts.logResult("Verify flash", step(0.8), "Chip verified successfully")
    ts.logResult("StLink VCC off", step(0.2), "OK")

    v = psu.waitVoltage(1, 12.0, tolerance=0.1, timeout=3)
    psu.ioOut(1, 8, 1)
    psu.ioOut(1, 8, 0)
    vRef = psu.getRefVoltage()
    ts.numericLimitTest("Supply 12V", v, 11.7, 12.3, "V")
    ts.numericLimitTest("Idle current", psu.getCurrent(1) * 1000, 80, 110, "mA")

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
    psu.ioOut(1, 9, 0)

def finalize():
    ts.logResult("StLink VCC off", step(0.1), "OK")
    ts.logResult("Fixture power off", step(0.3), "OK")


if __name__ == "__main__":
    print("Demo board test started")
    ts.run(steps, finalize, watch=watch)
    print("Demo board test finished")
