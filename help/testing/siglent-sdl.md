# Electronic load Siglent SDL1020X (SDL1000X series)

Drivers `testPlatform/instruments/siglent_sdl1020x.py` (class `SIGLENT_SDL1020X`, 150 V / 30 A / 200 W) on top of
the common SDL1000X driver `testPlatform/instruments/siglent_sdl.py` (`SiglentSDL`). LAN, raw SCPI socket port
**5025**. One line per function: in the code editor's **?** window hover a line and press *Insert* or *Copy*.

Every level and the input state are **read back** after they are written (one retry for a dropped command, then
`InstrumentError`). A value outside the model's range raises `ValueError`.

## Connect

```python
from instruments.siglent_sdl1020x import SIGLENT_SDL1020X

load = SIGLENT_SDL1020X("192.168.1.72")         # host, port=5025, timeout=3.0
load.checkModel()                               # "SDL1020X"; InstrumentError if another model answers (wrong IP)
load.idn()                                      # "Siglent Technologies,SDL1020X,SDL13…,1.1.1.23R4"
load.ping()                                     # True if it answers
```

Read-only check from a console (in `testPlatform/`): `python3 instruments/siglent_sdl1020x.py 192.168.1.72`.

## Modes and levels

Setting a mode never switches the input on — call `on()` or use `setup()`.

```python
load.setCC(0.5)                                 # constant current, A
load.setCV(10.0)                                # constant voltage, V (the load sinks what holds the voltage)
load.setCR(24.0)                                # constant resistance, Ω
load.setCP(6.0)                                 # constant power, W
load.setup("CC", 0.5)                           # mode + level + input on; setup("CR", 24, on=False) keeps it off
load.setMode("CC")                              # mode only: CC, CV, CR, CP
load.getMode()                                  # "CC"
load.getLevel()                                 # level of the present mode; getLevel("CP") of another one
load.setRange(irange=5, vrange=36)              # ranges of the present mode: 5 / 30 A, 36 / 150 V (low = finer)
load.setSlew(0.1, 0.1)                          # CC current slew rate rise / fall, A/µs
load.setVon(3.0)                                # start sinking only above 3 V (latch=True: keep sinking once started)
```

**CV against a current-limited supply** makes two regulators fight (load CV + supply limit): they oscillate and the
load pulls current peaks of several amperes out of the supply's capacitors. Keep the current down with the load's
own CC level instead.

## Input

```python
load.on()                                       # input on (checked)
load.off()                                      # input off — in finalize()
load.setInput(True)                             # on / off from a bool
load.isOn()                                     # input state
load.short(True)                                # short the input (maximum current of the range!); short(False)
```

## Measurements

```python
load.getVoltage()                               # input voltage, V
load.getCurrent()                               # A
load.getPower()                                 # W
load.getResistance()                            # Ω
v, i, p = load.measureAll()                     # all three
load.waitCurrent(0.5, tolerance=0.02, timeout=3)   # value once within the tolerance, None on timeout
```

## Protection and sense

```python
load.setCurrentProtection(1.1, delay=0.2)       # input off above 1.1 A for 0.2 s; None switches it off
load.setPowerProtection(17.0, delay=0.2)        # input off above 17 W; None switches it off
load.protection()                               # {"current": True, "power": True}
load.setSense4Wire(True)                        # remote sense (sense terminals wired to the UUT)
```

## Raw commands and errors

```python
load.query(":SOUR:CURR:SLEW:POS?")              # any query → text
load.write(":SOUR:LIST:STAT OFF")               # any command
load.errors()                                   # error queue, [] = no errors
load.close()                                    # close the connection (the next command opens it again)
```

## Complete example

`testPlatform/Siglent_SDL1020X_test.py` — the load on CH2 of PSU_CUSTOM6020 (max 16 V / 1 A): CC / CR / CP,
supply voltage steps, both instruments' meters against each other, lead resistance, a load step, switching.
A shorter one:

```python
"""Board output: 5 V rail under 0.5 A and 1 A load."""
from instruments.siglent_sdl1020x import SIGLENT_SDL1020X
from testStrategy import TestStrategy

ts = TestStrategy()
load = SIGLENT_SDL1020X("192.168.1.72")


def steps():
    load.setCurrentProtection(1.2, delay=0.2)
    for amps in (0.5, 1.0):
        load.setup("CC", amps)
        load.waitCurrent(amps)
        ts.numericLimitTest(f"5 V rail at {amps} A", load.getVoltage(), 4.85, 5.15, "V")


def finalize():
    load.off()
    load.setCurrentProtection(None)
    load.close()


ts.run(steps, finalize)
```
