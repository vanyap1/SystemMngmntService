"""Demo: operator input steps — text, drop-down, number, buttons, yes/no."""
import re
import time

from testStrategy import TestStrategy

ts = TestStrategy()


def steps():
    ts.logResult("Fixture power on", True, "OK")

    serial = ts.askText("Serial number", "Scan or type the board serial number (format VTP-123456)")
    ts.logResult("Serial number format", re.fullmatch(r"VTP-\d{6}", serial) is not None, serial)

    variant = ts.askChoice("Board variant", "Select the board variant under test",
                           ["VTP1 220V", "VTP1 110V", "VTP2 220V"], default="VTP1 220V")
    ts.stringMatchTest("Variant is supported", "yes" if variant.startswith("VTP1") else "no", "yes")

    ts.askButtons("Probe TP5", "Connect the DMM probe to TP5 (+) and GND (−), then press Continue",
                  ["Continue"])
    volts = ts.askNumber("TP5 reading", "Enter the voltage shown on the DMM",
                         lo=0, hi=30, units="V", default=12)
    ts.numericLimitTest("TP5 voltage", volts, 11.5, 12.5, "V")

    time.sleep(0.5)
    led = ts.askButtons("LED1 colour", "What colour is LED1?", ["Green", "Red", "Off"])
    ts.stringMatchTest("LED1 is green", led, "Green")

    beep = ts.askYesNo("Buzzer", "Press KEY1 on the board.\nDid the buzzer beep?")
    ts.booleanTest("Buzzer beeps on KEY1", beep, True)


def finalize():
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    ts.run(steps, finalize)
