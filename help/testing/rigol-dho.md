# Oscilloscope Rigol DHO800 / DHO900

Driver `testPlatform/instruments/rigol_dho.py` for the Rigol DHO800 / DHO900 series (DHO804, DHO814, DHO924 …; model classes in `rigol_dho804.py`, `rigol_dho924.py`) over
LAN — LXI raw SCPI socket, port **5555**. One line per function: in the code editor's **?** window hover a line
and press *Insert* or *Copy*. Channels are `1` … `4`; values in V, s, Hz.

A measurement the scope cannot make (no signal on the channel, out of screen) returns **`None`** — feed it to
`numericLimitTest` anyway: it becomes an ERROR row. No answer raises `InstrumentError`. See
[Instruments](instruments.md) for how devices are created and closed.

## Connect

```python
from instruments.rigol_dho924 import RIGOL_DHO924       # or RIGOL_DHO804 — the same functions

scope = RIGOL_DHO924("192.168.1.146")           # host, port=5555, timeout=5.0
scope.idn()                                     # "RIGOL TECHNOLOGIES,DHO924,DHO9A…,00.01.05"
scope.checkModel()                              # "DHO924"; InstrumentError if another model answers (wrong IP)
scope.ping()                                    # True if it answers
```

| Class | Model |
|---|---|
| `RIGOL_DHO804` | DHO804 — 4 channels, 70 MHz |
| `RIGOL_DHO924` | DHO924 — 4 channels, 250 MHz (192.168.1.146) |
| `RigolScope` (`instruments.rigol_dho`) | any DHO800 / DHO900, no model check |

Use the class of the model on your bench: `checkModel()` in the first step then tells at once when the address
points to another scope.

Read-only check from a console (in `testPlatform/`): `python3 instruments/rigol_dho.py 192.168.1.146`.

## Acquisition and trigger

```python
scope.autoset()                                 # AUTO: scale, timebase, trigger (waits 3 s)
scope.run()                                     # continuous acquisition
scope.stop()
scope.single()                                  # arm one acquisition
scope.waitTriggered(5)                          # after single(): True when captured, False on timeout
scope.forceTrigger()                            # trigger now
scope.triggerStatus()                           # "TD" triggered, "WAIT", "RUN", "AUTO", "STOP"
scope.clear()                                   # clear the waveforms on the screen
scope.setTrigger(1, 1.5, "POS", "AUTO")         # edge trigger: channel, level V, POS/NEG/RFAL, AUTO/NORM/SING
scope.setTriggerLevel(2.5)                      # move the level only
```

## Channels and timebase

```python
scope.setChannel(2, True)                       # show / hide a channel
scope.setScale(1, 0.5)                          # V/div
scope.getScale(1)                               # V/div
scope.setOffset(1, -1.0)                        # vertical offset, V
scope.setCoupling(1, "AC")                      # DC, AC or GND
scope.setProbe(1, 10)                           # probe 1×, 10× …
scope.setBandwidthLimit(1, True)                # 20 MHz limit on / off
scope.setTimebase(200e-6)                       # s/div
scope.getTimebase()                             # s/div
scope.setTimeOffset(0)                          # horizontal position, s
scope.getSampleRate()                           # Sa/s
```

## Measurements

```python
scope.getVoltPkPk(1)                            # peak-to-peak, V
scope.getVoltMax(1)                             # V
scope.getVoltMin(1)                             # V
scope.getVoltAmplitude(1)                       # top − base, V
scope.getVoltAvg(1)                             # mean, V
scope.getVoltRms(1)                             # RMS, V
scope.getFrequency(1)                           # Hz
scope.getPeriod(1)                              # s
scope.getDutyCycle(1)                           # positive duty cycle, %
scope.getRiseTime(1)                            # 10–90 %, s
scope.getFallTime(1)                            # s
scope.getPulseWidth(1)                          # positive pulse width, s (negative=True for the negative one)
scope.measure("OVERshoot", 1)                   # any item of the scope (MEAS_ITEMS in the driver)
scope.measureAvg("VPP", 1, n=5, delay=0.2)      # mean of n readings (None values skipped)
```

```python
scope.single()
scope.waitTriggered(2)
ts.numericLimitTest("Ripple 5V", scope.getVoltPkPk(1) * 1000, 0, 50, "mV")
ts.numericLimitTest("PWM frequency", scope.getFrequency(2), 19800, 20200, "Hz")
```

## Waveform and screenshot

```python
t, v = scope.getWaveform(1)                     # the points on the screen: times (s), volts (V)
ts.numericLimitTest("Max of capture", max(v), 4.8, 5.2, "V")
scope.screenshot("/home/vanya/shots/ripple.png")    # PNG of the screen, returns the path
```

`getWaveform` switches the waveform export to BYTE for the transfer and puts the scope's setting back.

## Errors and the connection

```python
scope.errors()                                  # the scope's error queue, [] = none
scope.checkErrors()                             # raise InstrumentError if the queue is not empty
scope.close()                                   # close the socket (the next command opens it again)
```

The scope never answers a setting command, so a mistyped value shows up only in `errors()` — call
`checkErrors()` after a group of settings. Generic SCPI functions (`query`, `write`, `reset`, `waitDone` …):
see [Instruments](instruments.md).
