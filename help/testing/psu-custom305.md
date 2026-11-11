# Power supply PSU_CUSTOM305 (PSU Ethernet Controller)

Driver `testPlatform/instruments/psu_custom305.py` for the single-channel **PSU Ethernet Controller** (FW 2.0,
web page `http://192.168.1.99/`) that drives a 30 V / 5 A bench supply through its REM line. One line per
function: in the code editor's **?** window hover a line and press *Insert* or *Copy*. Values are V, A, W; there
is one channel, so the functions take no channel number (unlike [PSU_CUSTOM6020](psu-custom6020.md)).

Raw SCPI-99 over TCP port **8080**, one connection per command. Setting commands answer `OK`; an
`ERROR: <code>,<text>` answer or no answer raises `PsuError`, a wrong argument `ValueError`.

## Connect

```python
from instruments.psu_custom305 import PSU_CUSTOM305, PsuError

psu = PSU_CUSTOM305("192.168.1.99")             # host, port=8080, timeout=3.0, retries=5, auto_remote=True
psu.ping()                                      # True if the controller answers
psu.identify()                                  # "PSU-ETH,PSU-ETH,0,FW 2.0 Oct 31 2026"
```

Read-only check from a console (switches nothing): `python3 instruments/psu_custom305.py 192.168.1.99`
(in `testPlatform/`).

## Remote control (REM)

Without REM the supply belongs to its front panel: the controller only measures, setpoints and `OUTP ON` are
refused with `-221`. With `auto_remote=True` (default) the first refused setting command switches REM on and is
sent again. REM on always starts with the output **off**.

```python
psu.setRemote(True)                             # take over the supply (output starts off)
psu.isRemote()                                  # True / False
psu.local()                                     # hand it back to the front panel — last line of finalize()
psu.setRemote(False)                            # the same as local()
```

## Setpoints and output

```python
psu.setVoltage(12.0)                            # voltage setpoint, V
psu.setCurrent(0.5)                             # current limit, A
psu.apply(12.0, 0.5)                            # both in one command (APPLy)
psu.setup(12.0, 0.5)                            # setpoints + output on; setup(12.0, 0.5, on=False) keeps it off
psu.on()                                        # output on
psu.off()                                       # output off (DAC to 0 V); does nothing without REM
psu.setOutput(True)                             # on / off from a bool
psu.isOn()                                      # output state
psu.getSetVoltage()                             # setpoints read back, V / A
psu.getSetCurrent()
psu.getLimits()                                 # (60.0, 5.0) — highest allowed setpoints of the controller
```

## Measurements

```python
psu.getVoltage()                                # measured output voltage, V (0.5 s average)
psu.getCurrent()                                # A
psu.getPower()                                  # W
v, i, w = psu.measureAll()                      # all three from one request
psu.waitVoltage(12.0, tolerance=0.1, timeout=5) # value once within the tolerance, None on timeout
psu.getData()                                   # everything at once (PSU:DATA?) as a dict
```

`getData()` keys: `voltage`, `current`, `power`, `set_voltage`, `set_current`, `output`, `remote`, `adc_ok`,
`dac_ok`, `dig_out`, `dig_in`, `v_max`, `i_max`, `cal` (state of the automatic calibration, `IDLE`).

## Digital IO of the controller

Three outputs O1..O3 and three inputs IN1..IN3 on the controller board; "all" values are bit masks, bit0 = 1.

```python
psu.digOut(1, 1)                                # switch O1 on
psu.digOutAll(0b101)                            # O1 and O3 on, O2 off
psu.digOutRead()                                # all outputs as bits; digOutRead(2) → 0 / 1
psu.digIn()                                     # all inputs as bits, e.g. 7; digIn(3) → 0 / 1
```

## EXT_IO modules

Relay / input cards on the controller's I²C bus, configured on its web page (*EXT_IO* tab).

```python
psu.ioList()                                    # [{"n": 1, "type": "MIX", "addr": "25", "name": "IO module", "labels": []}]
psu.ioState()                                   # raw state lines n|type|addr|online|pins|setpoint; ioState(1) = one module
psu.ioOut(1, 3, 1)                              # module 1, output 3 on → actual level
psu.ioOutRead(1, 3)                             # level of an output
psu.ioIn(1, 2)                                  # level of an input
psu.ioOutAll(1, 0x0005)                         # all outputs of module 1 from a bit mask
```

## System

```python
psu.selfTest()                                  # *TST? — True when the meter and the DAC are OK
psu.info()                                      # SYSTem:INFO? as a dict (firmware, reset cause, network …)
psu.errors()                                    # error queue, [] = no errors
psu.clearStatus()                               # *CLS
psu.reset()                                     # *RST — output off, setpoints 0 (REM unchanged)
psu.query("CONF?")                              # any command → answer text (configuration, calibration …)
psu.command("VOLT 5")                           # setting command with the auto REM of the driver
psu.close()                                     # nothing to close (one connection per command)
```

Calibration and the controller settings (`CAL:…`, `CONF:SET`) are done on the web page; `query()` reaches them
from a script if really needed.

## Complete example

```python
"""Board supplied from PSU_CUSTOM305: inrush, idle current, fixture relay on O1."""
from instruments.psu_custom305 import PSU_CUSTOM305
from testStrategy import TestStrategy

ts = TestStrategy()
psu = PSU_CUSTOM305("192.168.1.99")


def steps():
    ts.logResult("PSU self test", psu.selfTest(), psu.identify())
    psu.digOut(1, 1)                            # fixture relay: board connected
    psu.setup(12.0, 0.5)
    ts.numericLimitTest("Supply 12V", psu.waitVoltage(12.0, 0.1, 3), 11.7, 12.3, "V")
    ts.numericLimitTest("Idle current", psu.getCurrent() * 1000, 35, 50, "mA")


def finalize():
    psu.off()
    psu.digOutAll(0)
    psu.local()


ts.run(steps, finalize)
```
