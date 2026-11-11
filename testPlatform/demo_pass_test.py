"""Demo: full board sequence where every step passes (uses the bench PSU at 192.168.1.91)."""

import os
import random
import time
from instruments.psu_custom6020 import PSU_CUSTOM6020
from instruments.psu_custom305 import PSU_CUSTOM305
from instruments.rigol_dho924 import RIGOL_DHO924
from instruments.ssh_term import SshTerm
from testStrategy import TestStrategy
from testWatch import TestWatch, file_flag

from instruments.modbus import ModbusRTU, to_ascii

ts = TestStrategy()


#uutTerm=uutSSH(192.168.x.x, "user", password)
scope = RIGOL_DHO924("192.168.1.146")
uutTerm = SshTerm("192.168.1.70", "pi", "0000")
psu = PSU_CUSTOM6020("192.168.1.91")
psu2 = PSU_CUSTOM305("192.168.1.99")

mb = ModbusRTU("/dev/ttyUSB0", 115200, unit=1, retries=1)

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

def modbusRead():
    ts.section("Modbus Tesla CCVE")
    regs = mb.readHolding(0, 12)
    ts.stringMatchTest("Firmware", to_ascii(regs[4:6]), "3.47")
    ts.stringMatchTest("Model", to_ascii(regs[7:11]).strip(), "J1772_0")
    ts.numericLimitTest("State", regs[2], 0, 9, "")

def calc_b(a, b):
    return a+b

def steps():
    psu.ioOut(1, 9, 1)
    idn = psu.identify().split("\n")[1]
    idn2 = psu2.identify()
    psu.setVoltage(1, 12.0)                         # voltage preset, V
    print(idn)
    print(idn2)
    modbusRead()
    psu.on(1)
    #ts.logResult("Uname", True, uutTerm.cmd("whoami"))
    ts.section("Oscilloscope")
    ts.logResult("Scope model", True, scope.checkModel())   # ERROR row if another scope answers at this IP
    scope.autoset()                                         # AUTO, the driver waits 3 s for it to settle
    ts.numericLimitTest("CH1 voltage Vpp", scope.getVoltPkPk(1), 2.9, 3.1, "V")
    ts.numericLimitTest("CH1 frequency", scope.getFrequency(1), 990, 1010, "Hz")
    
    ts.logResult("Serial number", True, ts.serial or "not given")    # the Serial field of the Tests page (--sn)
    ts.logResult("PSU info", True, idn)
    ts.logResult("Fixture power on", step(0.3), "OK")
    ts.logResult("StLink VCC on", step(0.2), "OK")
    print(calc_b(150,300))
    
    print("Flashing test firmware DEMO_EOLT_V1.hex ...")
    a = 100
    b = 200
    c = a + b

    
                                       # output on

    


    ts.logResult("Erase chip", step(1.0), "Chip erased successfully")
    ts.logResult("Flash chip", step(1.5), "Chip flashed successfully")
    ts.logResult("Verify flash", step(0.8), "Chip verified successfully")
    ts.logResult("StLink VCC off", step(0.2), "OK")

    v = psu.waitVoltage(1, 12.0, tolerance=0.1, timeout=3)
    psu.ioOut(1, 8, 1)
    psu.ioOut(1, 8, 0)
    vRef = psu.getRefVoltage()
    ts.numericLimitTest("Supply 12V", v, 11.7, 12.3, "V")
    ts.numericLimitTest("Idle current", psu.getCurrent(1) * 1000, 70, 110, "mA")

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
