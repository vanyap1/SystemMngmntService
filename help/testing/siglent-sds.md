# Oscilloscope Siglent SDS802X HD (SDS800X HD series)

Driver `testPlatform/instruments/siglent_sds802xhd.py` (class `SIGLENT_SDS802XHD`, 2 channels, 70 MHz, 2 GSa/s,
12 bit) on top of the common SDS800X HD driver `testPlatform/instruments/siglent_sds.py` (`SiglentSDS`). LAN, raw
SCPI socket port **5025**. One line per function: in the code editor's **?** window hover a line and press
*Insert* or *Copy*. Channels are `1`, `2` (`1` … `4` on the 4-channel models); values in V, s, Hz.

A measurement the scope cannot make (no periodic signal for a frequency, no edge for a rise time) returns
**`None`** — feed it to `numericLimitTest` anyway: it becomes an ERROR row. No answer raises `InstrumentError`.
See [Instruments](instruments.md) for how devices are created and closed.

## Connect

```python
from instruments.siglent_sds802xhd import SIGLENT_SDS802XHD

scope = SIGLENT_SDS802XHD("192.168.1.75")       # host, port=5025, timeout=5.0
scope.idn()                                     # "Siglent Technologies,SDS802X HD,SDS08A…,4.8.12.1.1.6.5"
scope.checkModel()                              # "SDS802X HD"; InstrumentError if another model answers (wrong IP)
scope.ping()                                    # True if it answers
```

| Class | Model |
|---|---|
| `SIGLENT_SDS802XHD` | SDS802X HD — 2 channels, 70 MHz (192.168.1.75) |
| `SiglentSDS` (`instruments.siglent_sds`) | any SDS800X HD, 4 channels, no model check |

Read-only check from a console (in `testPlatform/`): `python3 instruments/siglent_sds802xhd.py 192.168.1.75`.

## Output ripple

```python
scope.setupRipple(1)                            # probe 1×, AC, 50 mV/div, offset 0, 5 µs/div, 20 MHz, trigger AUTO
scope.setupRipple(1, volts_per_div=0.02, seconds_per_div=2e-6, bw_limit=False, probe=10)   # other settings
scope.getRipple(1)                              # worst peak-to-peak of 10 readings, V (n=10, delay=0.2)
```

`setupRipple` reads back coupling, scale, timebase and probe (`InstrumentError` if the scope did not take them);
`probe=None` keeps the probe setting of the scope. Trigger AUTO keeps the acquisitions fresh without a trigger.

```python
scope.setupRipple(1)
ripple = scope.getRipple(1, n=5)
ts.numericLimitTest("Ripple 12V", None if ripple is None else ripple * 1000, 0, 120, "mV")
```

## Acquisition and trigger

```python
scope.autoset()                                 # AUTO setup (waits 4 s)
scope.run()                                     # acquire continuously
scope.stop()                                    # stop
scope.single()                                  # one acquisition (trigger mode SINGle) …
scope.waitTriggered(5)                          # … wait until it is complete; False on timeout
scope.setTriggerMode("AUTO")                    # AUTO, NORMal, SINGle
scope.getTriggerMode()                          # "AUTO" / "NORMal" / "SINGle"
scope.triggerStatus()                           # "Arm", "Ready", "Auto", "Trig'd", "Stop", "Roll"
scope.setTrigger(1, level=0.5, slope="RISing", mode="NORMal")   # edge trigger: RISing / FALLing / ALTernate
scope.setTriggerLevel(0.5)                      # V
```

## Vertical and horizontal

```python
scope.setChannel(1, True)                       # show / hide a channel
scope.isChannelOn(1)                            # True / False
scope.setScale(1, 0.05)                         # V/div
scope.getScale(1)
scope.setOffset(1, 0)                           # V
scope.getOffset(1)
scope.setCoupling(1, "AC")                      # DC, AC, GND
scope.getCoupling(1)                            # "AC"
scope.setProbe(1, 1)                            # probe ratio 1, 10, 100 …
scope.getProbe(1)                               # 1.0
scope.setBandwidthLimit(1, True)                # 20 MHz limit on / off
scope.setTimebase(5e-6)                         # s/div
scope.getTimebase()
scope.setTimeOffset(0)                          # trigger delay (horizontal position), s
scope.getTimeOffset()
scope.getSampleRate()                           # Sa/s
```

## Measurements

The driver uses the scope's simple measurement (switched on by the first call, source = the channel asked for).

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
scope.measure("OVSP", 1)                        # any item of the scope (MEAS_ITEMS in the driver)
scope.measureStats("PKPK", 1, n=10, delay=0.2)  # (min, mean, max) of n readings, None if none was valid
scope.measureAvg("PKPK", 1, n=5, delay=0.2)     # mean of n readings
```

## Waveform and screenshot

```python
scope.single(); scope.waitTriggered(5)          # stop on one acquisition first
t, v = scope.getWaveform(1, points=10000)       # times (s, 0 = trigger), volts — decimated to ~points
scope.screenshot(data_path("ripple.png"))       # PNG of the screen, returns the path
```

`getWaveform` reads 16-bit data (`:WAVeform:WIDTh WORD`); decimation keeps every n-th point, so the peak-to-peak of
the result can be lower than the scope's own PKPK measurement.

## Errors and the connection

```python
scope.errors()                                  # the scope's error queue, [] = none
scope.checkErrors()                             # raise InstrumentError if the queue is not empty
scope.close()                                   # close the socket (the next command opens it again)
```

The scope never answers a setting command, so a mistyped value shows up only in `errors()` — call
`checkErrors()` after a group of settings. Generic SCPI functions (`query`, `write`, `reset`, `waitDone` …):
see [Instruments](instruments.md). Demo script: `testPlatform/Siglent_SDS802XHD_test.py`.
