"""Demo: the script crashes mid-sequence (exception) — finalization still runs, verdict ERROR."""
import time

from testStrategy import TestStrategy

ts = TestStrategy()


def open_dmm(port):
    raise ConnectionError(f"cannot open DMM on {port}")


def steps():
    ts.logResult("Fixture power on", True, "OK")
    time.sleep(0.5)
    ts.numericLimitTest("Supply 5V", 5.01, 4.85, 5.15, "V")
    time.sleep(0.5)
    print("Connecting to multimeter...")
    dmm = open_dmm("/dev/ttyUSB7")
    ts.numericLimitTest("Minus 8V", dmm.getVolt(), 7.3, 8.3, "V")


def finalize():
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    ts.run(steps, finalize)
