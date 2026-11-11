# Electronic load OWON OEL

Driver `testPlatform/instruments/owon_oel.py` for OWON DC electronic loads (OEL1515, OEL1530, OEL3120 …) over
**USB-serial** (115200 8N1) or **LAN** (raw SCPI socket, port 3000 by default). Values in V, A, Ω, W.

Setting a mode never switches the input on by itself — call `on()` or `setup()`. Always switch the load off in
`finalize()`. See [Instruments](instruments.md).

## Connect

```python
from instruments.owon_oel import OWON_OEL

load = OWON_OEL(serial="/dev/ttyUSB1")          # USB, baud=115200
load = OWON_OEL(host="192.168.1.61", port=3000) # LAN models
load.idn()
```

## Modes and input

```python
load.setCC(1.5)                                 # constant current, A (input stays off)
load.setCV(4.8)                                 # constant voltage, V
load.setCR(10)                                  # constant resistance, Ω
load.setCP(20)                                  # constant power, W
load.setup("CC", 1.5)                           # mode + value + input on in one call
load.setup("CR", 33, on=False)                  # preset only
load.on()                                       # input on — the load sinks
load.off()                                      # input off (finalize!)
load.isOn()                                     # True / False
load.getMode()                                  # "CC", "CV", "CR" or "CP"
load.local()                                    # front panel keys back
```

## Measurements

```python
load.getVoltage()                               # input voltage, V
load.getCurrent()                               # input current, A
load.getPower()                                 # input power, W
load.waitCurrent(1.5, tolerance=0.05, timeout=5)   # wait until the current settles; returns the last reading
```

```python
load.setup("CC", 2.0)
load.waitCurrent(2.0)
ts.numericLimitTest("Output at 2 A", load.getVoltage(), 11.6, 12.4, "V")
load.off()
```

## Another OWON model

The SCPI words are in `OWON_OEL.COMMANDS` — change one in the script if the load answers "command error":

```python
load.COMMANDS["mode"] = ":SOUR:FUNC {}"         # {} = CURR / VOLT / RES / POW
load.COMMANDS["meas_v"] = ":MEAS:VOLT?"
```
