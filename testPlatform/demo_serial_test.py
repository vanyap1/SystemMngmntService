"""Demo: uses the serial number from the Test Run panel (--sn); valid: "test" or VTP-123456."""
import re
import time

from testStrategy import TestStrategy

ts = TestStrategy()

def steps():
    serial = ts.serial
    print(f"Unit under test: {serial or '<no serial>'}")
    if not ts.logResult("Serial number provided", bool(serial), serial or "empty — fill the Serial field"):
        return
    valid = serial.lower() == "test" or re.fullmatch(r"VTP-\d{6}", serial) is not None
    if not ts.logResult("Serial number valid", valid, serial):
        return   # nothing else to test on an unknown unit (also without stop-on-fail)

    ts.logResult("Fixture power on", True, "OK")
    time.sleep(0.5)
    ts.numericLimitTest("Supply 5V", 5.02, 4.85, 5.15, "V")
    time.sleep(0.5)
    ts.stringMatchTest("Serial written to EEPROM", serial, serial)


def finalize():
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    ts.run(steps, finalize)
