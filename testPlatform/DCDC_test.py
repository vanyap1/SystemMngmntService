import os
import random
import time
import gpiod
from datetime import datetime, timezone

from testStrategy import TestStrategy
from instruments.siglent_spd1305x import SIGLENT_SPD1305X
from instruments.siglent_sdl1020x import SIGLENT_SDL1020X


load = SIGLENT_SDL1020X("192.168.1.72")         # host, port=5025, timeout=3.0
psu = SIGLENT_SPD1305X("192.168.1.74")          # host, port=5025, timeout=3.0
psu.setCurrent(3.0)                             # current limit, A (0…5)
psu.setVoltage(24.0)                            # voltage setpoint, V (0…30)
                        
load.setCC(0.5)                                 # constant current, A



ts = TestStrategy()


uut1_tp5 = gpiod.find_line("out3")
uut1_tp3 = gpiod.find_line("out4")
uut1_tp1 = gpiod.find_line("out5")  # VIN

dso_tp6 = gpiod.find_line("out2")
dso_tp5 = gpiod.find_line("out0")
dso_tp3 = gpiod.find_line("out1")


if (
    not uut1_tp5
    or not uut1_tp3
    or not uut1_tp1
    or not dso_tp6
    or not dso_tp5
    or not dso_tp3
):
    print("dev cannot find line for user button (net_lo_ntc). Check your DT configuration.")
    exit(1)

uut1_tp5.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
uut1_tp3.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
uut1_tp1.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
dso_tp6.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
dso_tp5.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
dso_tp3.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])


def step(seconds):
    time.sleep(seconds)
    return True


def steps():
    ts.logResult("PSU info", True, psu.idn())
    ts.logResult("LOAD info", True, load.idn())
    uut1_tp3.set_value(0)
    dso_tp3.set_value(0)
    uut1_tp1.set_value(0)
    psu.on()
    load.on()  

    
    load.setCC(0.5)
    time.sleep(1);
    ts.numericLimitTest("CH1 CURR 0.5A", load.getVoltage(), 11.7, 12.3, "V") 
    load.setCC(1.0)
    time.sleep(1);
    ts.numericLimitTest("CH1 CURR 1.0A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(1.5)
    time.sleep(1);
    ts.numericLimitTest("CH1 CURR 1.5A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(2.0)
    time.sleep(1);
    ts.numericLimitTest("CH1 CURR 2.0A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(2.5)
    time.sleep(1);
    ts.numericLimitTest("CH1 CURR 2.5A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(3)
    time.sleep(1);
    ts.numericLimitTest("CH1 CURR 3.0A", load.getVoltage(), 11.7, 12.3, "V")
    load.off()
    psu.off()
    
    uut1_tp3.set_value(1)
    dso_tp3.set_value(1)
    uut1_tp1.set_value(1)
    time.sleep(1);

    uut1_tp5.set_value(0)
    dso_tp5.set_value(0)
    uut1_tp1.set_value(0)
    psu.on() 
    load.on()  

    load.setCC(0.5)
    time.sleep(1);
    ts.numericLimitTest("CH2 CURR 0.5A", load.getVoltage(), 11.7, 12.3, "V") 
    load.setCC(1.0)
    time.sleep(1);
    ts.numericLimitTest("CH2 CURR 1.0A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(1.5)
    time.sleep(1);
    ts.numericLimitTest("CH2 CURR 1.5A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(2.0)
    time.sleep(1);
    ts.numericLimitTest("CH2 CURR 2.0A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(2.5)
    time.sleep(1);
    ts.numericLimitTest("CH2 CURR 2.5A", load.getVoltage(), 11.7, 12.3, "V")
    load.setCC(3)
    time.sleep(1);
    ts.numericLimitTest("CH2 CURR 3.0A", load.getVoltage(), 11.7, 12.3, "V")
    load.off()
    psu.off()
    load.off()
    psu.off()
    
    uut1_tp5.set_value(1)
    dso_tp5.set_value(1)
    uut1_tp1.set_value(1)
    time.sleep(1);





def finalize():
    uut1_tp5.set_value(1)
    uut1_tp3.set_value(1)
    uut1_tp1.set_value(1)
    dso_tp6.set_value(1)
    dso_tp5.set_value(1)
    dso_tp3.set_value(1)
    ts.logResult("Test Stop", step(0.1), "OK")
    


if __name__ == "__main__":
    print(f"Test started at {datetime.now()}")
    ts.run(steps, finalize)
    print(f"Test stopped at {datetime.now()}")
