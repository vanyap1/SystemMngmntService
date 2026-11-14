import re
import time

from testStrategy import TestStrategy
from instruments.siglent_spd1305x import SIGLENT_SPD1305X


ts = TestStrategy()

psu = SIGLENT_SPD1305X("192.168.1.74")          # host, port=5025, timeout=3.0
       


def steps():
    ts.section("Siglent communication test")
    ts.logResult("PSU model", True, psu.checkModel())
    ts.logResult("PSU IDN", True, psu.idn())
    ts.logResult("Ping", True, str(psu.ping()))
    ts.logResult("PSU Ver", True, psu.version())
    ts.logResult("PSU Network", True, str(psu.network()))

    psu.setVoltage(12.0)                            # voltage setpoint, V (0…30)
    psu.setCurrent(0.5)                             # current limit, A (0…5)
    psu.on()                                        # output on (checked in the status word)


    ts.numericLimitTest("PSU check Voltage", psu.getVoltage(), 11.8, 12.4, "V")
    ts.numericLimitTest("PSU check Current", psu.getCurrent(), -0.1, 1, "A")


    psu.off()                                       # output off

                                    
    

def finalize():
    ts.logResult("Fixture power off", True, "OK")


if __name__ == "__main__":
    ts.run(steps, finalize)