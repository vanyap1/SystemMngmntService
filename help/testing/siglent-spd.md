# Power supply Siglent SPD1305X (SPD1000X series)

Drivers `testPlatform/instruments/siglent_spd1305x.py` (class `SIGLENT_SPD1305X`, 30 V / 5 A) on top of the common
SPD1000X driver `testPlatform/instruments/siglent_spd.py` (`SiglentSPD`). LAN, raw SCPI socket port **5025**.
One line per function: in the code editor's **?** window hover a line and press *Insert* or *Copy*. One channel,
values in V, A, W.

Every setpoint is **read back** after it is written — the SPD sometimes drops a command sent right after another
one; the driver sends it once more and raises `InstrumentError` if it still did not take. No answer raises
`InstrumentError`, a value outside the model's range `ValueError`.

## Connect

```python
from instruments.siglent_spd1305x import SIGLENT_SPD1305X

psu = SIGLENT_SPD1305X("192.168.1.74")          # host, port=5025, timeout=3.0
psu.checkModel()                                # "SPD1305X"; InstrumentError if another model answers (wrong IP)
psu.idn()                                       # "Siglent Technologies,SPD1305X,SPD13…,2.1.2.12R3,V2.0"
psu.ping()                                      # True if it answers
psu.version()                                   # firmware "2.1.2.12R3"
psu.network()                                   # {"ip": …, "mask": …, "gateway": …, "dhcp": "OFF"}
```

Read-only check from a console (in `testPlatform/`): `python3 instruments/siglent_spd1305x.py 192.168.1.74`.

## Setpoints and output

```python
psu.setVoltage(12.0)                            # voltage setpoint, V (0…30)
psu.setCurrent(0.5)                             # current limit, A (0…5)
psu.setup(12.0, 0.5)                            # both + output on; setup(12.0, 0.5, on=False) keeps it off
psu.on()                                        # output on (checked in the status word)
psu.off()                                       # output off
psu.setOutput(True)                             # on / off from a bool
psu.isOn()                                      # output state
psu.getSetVoltage()                             # setpoints read back, V / A
psu.getSetCurrent()
```

## Measurements

```python
psu.getVoltage()                                # measured output voltage, V
psu.getCurrent()                                # A
psu.getPower()                                  # W
v, i, w = psu.measureAll()                      # all three
psu.waitVoltage(12.0, tolerance=0.1, timeout=5) # value once within the tolerance, None on timeout
```

## Status and modes

```python
psu.status()                                    # {"cc", "output", "wire4", "timer", "waveform", "raw"} from SYST:STAT?
psu.isCC()                                      # True = constant current (the limit is reached), False = CV
psu.setSense4Wire(True)                         # 4-wire remote sense; False = 2-wire
```

## Timer and memories

```python
psu.setTimer(1, 5.0, 1.0, 10)                   # timer step 1..5: volts, amps, seconds
psu.getTimer(1)                                 # (5.0, 1.0, 10.0)
psu.timer(True)                                 # run the timer sequence; timer(False) stops it
psu.save(1)                                     # store the setpoints into memory 1..5
psu.recall(1)                                   # load them back
```

## Raw commands and errors

```python
psu.query("CH1:VOLT?")                          # any query → text (empty lines left by the supply are skipped)
psu.queryFloat("MEAS:CURR?")                    # any query → float
psu.write("OUTP:WAVE CH1,ON")                   # any command without an answer
psu.errors()                                    # error queue, [] = no errors, e.g. ["-113,Undefined header,OUTPut?"]
psu.close()                                     # close the connection (the next command opens it again)
```

## Complete example

```python
"""Board powered from the Siglent SPD1305X: supply voltage and idle current."""
from instruments.siglent_spd1305x import SIGLENT_SPD1305X
from testStrategy import TestStrategy

ts = TestStrategy()
psu = SIGLENT_SPD1305X("192.168.1.74")


def steps():
    ts.logResult("PSU model", True, psu.checkModel())
    psu.setup(12.0, 0.5)
    ts.numericLimitTest("Supply 12V", psu.waitVoltage(12.0, 0.1, 3), 11.8, 12.2, "V")
    ts.numericLimitTest("Idle current", psu.getCurrent() * 1000, 35, 50, "mA")
    ts.logResult("No current limit", not psu.isCC(), "CV")


def finalize():
    psu.off()
    psu.close()


ts.run(steps, finalize)
```
