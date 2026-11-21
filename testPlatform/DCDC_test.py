import os
import random
import time
import gpiod
from datetime import datetime, timezone

from testStrategy import TestStrategy
from instruments.siglent_spd1305x import SIGLENT_SPD1305X
from instruments.siglent_sdl1020x import SIGLENT_SDL1020X
from instruments.siglent_sds802xhd import SIGLENT_SDS802XHD


load = SIGLENT_SDL1020X("192.168.1.72")         # host, port=5025, timeout=3.0
psu = SIGLENT_SPD1305X("192.168.1.74")          # host, port=5025, timeout=3.0
psu.setCurrent(3.0)                             # current limit, A (0…5)
psu.setVoltage(24.0)                            # voltage setpoint, V (0…30)
                        
load.setCC(0.5)                                 # constant current, A
scope = SIGLENT_SDS802XHD("192.168.1.75")       # host, port=5025, timeout=5.0

SCOPE_CH = 1                                    # scope input switched to the UUT outputs by the dso_tp* relays
RIPPLE_MAX_MV = 120                             # output ripple limit, mV peak-to-peak



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


def check_output(name, amps):
    """Output voltage, then its ripple (scope: probe 1x, AC, 50 mV/div, 5 us/div) at a load current."""
    load.setCC(amps)
    time.sleep(1)
    ts.numericLimitTest(f"{name} CURR {amps:.1f}A", load.getVoltage(), 11.7, 12.3, "V")
    ripple = scope.getRipple(SCOPE_CH, n=5)
    ts.numericLimitTest(f"{name} RIPPLE {amps:.1f}A", None if ripple is None else round(ripple * 1000, 1),
                        0, RIPPLE_MAX_MV, "mV")


def steps():
    ts.logResult("PSU info", True, psu.idn())
    ts.logResult("LOAD info", True, load.idn())
    ts.logResult("DSO info", True, scope.checkModel())
    scope.setupRipple(SCOPE_CH, volts_per_div=0.05, seconds_per_div=5e-6, probe=1)
    uut1_tp3.set_value(0)
    dso_tp3.set_value(0)
    uut1_tp1.set_value(0)
    psu.on()
    load.on()  

    
    for amps in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        check_output("CH1", amps)
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

    for amps in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        check_output("CH2", amps)
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
