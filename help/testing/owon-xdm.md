# Bench multimeter OWON XDM

Driver `testPlatform/instruments/owon_xdm.py` for OWON bench multimeters (XDM1041, XDM1241, XDM2041, XDM3051 …)
over **USB-serial** (115200 8N1) or **LAN** (raw SCPI socket, port 3000 by default — check the meter's network
menu). Values in V, A, Ω, F, Hz, °C; an overload (`OVLD`, open input) returns **`None`**.

See [Instruments](instruments.md) for how devices are created and closed.

## Connect

```python
from instruments.owon_xdm import OWON_XDM

dmm = OWON_XDM(serial="/dev/ttyUSB0")            # USB (CH340 / CP210x), baud=115200
dmm = OWON_XDM(host="192.168.1.60", port=3000)   # LAN models
dmm.idn()                                       # "OWON,XDM1041,…"
```

## Measurements

The function is switched only when it changes (the relays click and the reading must settle), then the first
reading after the switch is thrown away — so a series of `getVoltDC()` calls is fast.

```python
dmm.getVoltDC()                                 # DC voltage, V (auto range)
dmm.getVoltDC("5")                              # fixed range — the range word of your meter
dmm.getVoltAC()                                 # AC RMS, V
dmm.getCurrentDC()                              # DC current, A — mind the input jack
dmm.getCurrentAC()                              # AC RMS, A
dmm.getResistance()                             # Ω, None = open
dmm.getContinuity()                             # Ω of the continuity test, None = open
dmm.getDiode()                                  # forward voltage, V
dmm.getCapacitance()                            # F (slow: waits 2 s after the switch)
dmm.getFrequency()                              # Hz
dmm.getTemperature()                            # °C with the PT100 probe
```

```python
ts.numericLimitTest("Rail 3V3", dmm.getVoltDC(), 3.2, 3.4, "V")
ts.numericLimitTest("Shunt", dmm.getResistance() * 1000, 9.8, 10.2, "mΩ")
```

## Function, rate, repeated readings

```python
dmm.configure("vdc")                            # vdc vac idc iac res cont diode cap freq temp (+ range)
dmm.read()                                      # value on the display in the current function
dmm.readAvg(5, 0.2)                             # mean of 5 readings, overloads skipped
dmm.setRate("S")                                # S slow (best resolution), M, F fast
dmm.local()                                     # front panel keys back — call it in finalize()
```

## Another OWON model

The SCPI words differ a little between OWON series. They are in `OWON_XDM.COMMANDS`; if the meter answers
"command error", change the word in the script:

```python
dmm.COMMANDS["read"] = "MEAS?"                   # e.g. a model without MEAS1?
dmm.COMMANDS["vdc"] = "CONF:VOLT:DC"
```

Find the right words with the HW Utils **Terminal** (serial, 115200, line end LF): `*IDN?`, `MEAS1?`, `FUNC?`.
