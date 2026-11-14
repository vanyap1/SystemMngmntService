# Generator Siglent SDG1032X (SDG series)

Drivers `testPlatform/instruments/siglent_sdg1032x.py` (class `SIGLENT_SDG1032X`, 2 channels, 30 MHz) on top of
the common SDG driver `testPlatform/instruments/siglent_sdg.py` (`SiglentSDG`). LAN, raw SCPI socket port **5025**.
One line per function: in the code editor's **?** window hover a line and press *Insert* or *Copy*.
Channels `1` and `2`; frequency Hz, amplitude **Vpp**, offset V, phase °, times s, duty / symmetry %.

The generator silently limits a value it cannot do (amplitude above the range for the load, frequency above the
waveform's maximum). Every `set…` function therefore reads the value back and raises `InstrumentError`, e.g.
*"CH1 AMP: 15 asked, the generator has 10.0"*. A wrong argument raises `ValueError`.

## Connect

```python
from instruments.siglent_sdg1032x import SIGLENT_SDG1032X

gen = SIGLENT_SDG1032X("192.168.1.73")          # host, port=5025, timeout=3.0
gen.checkModel()                                # "SDG1032X"; InstrumentError if another model answers (wrong IP)
gen.idn()                                       # "Siglent Technologies,SDG1032X,SDG1XDDXA01104,1.01.01.33R8"
gen.ping()                                      # True if it answers
```

Read-only check from a console (in `testPlatform/`): `python3 instruments/siglent_sdg1032x.py 192.168.1.73`.

## Output and load

Set the load first: amplitudes are what the generator delivers **into this load** (into 50 Ω the open-circuit
voltage is double).

```python
gen.setLoad(1, 50)                              # 50 Ω termination; setLoad(1, "HZ") = high impedance (default)
gen.on(1)                                       # output on
gen.off(1)                                      # output off
gen.allOff()                                    # both outputs off — in finalize()
gen.setOutput(1, True)                          # on / off from a bool
gen.isOn(1)                                     # output state
gen.outputState(1)                              # {"on": False, "load": "HZ", "polarity": "NOR"}
gen.invert(1, True)                             # inverted polarity; invert(1, False) = normal
```

## Waveforms in one line

Each one sets the waveform and its parameters and switches the output on (`on=False` keeps it off).

```python
gen.sine(1, 1000, 2.0)                          # sine 1 kHz, 2 Vpp, offset 0
gen.square(1, 10e3, 3.3, offset=1.65, duty=25)  # 0…3.3 V square, 25 % duty
gen.ramp(1, 100, 5.0, symmetry=50)              # triangle; symmetry 0 / 100 = saw
gen.pulse(1, 1000, 5.0, 100e-6, offset=2.5)     # 0…5 V pulse, 100 µs wide
gen.dc(2, 2.5)                                  # constant 2.5 V
gen.noise(2, 0.1, mean=0.0)                     # gaussian noise, stdev 0.1 V
gen.arb(1, "Cardiac", 1.2, 1.0)                 # built-in arbitrary wave by name, 1.2 Hz, 1 Vpp
gen.setup(1, "SINE", 50, 4.0, offset=0, on=True)   # generic: waveform, Hz, Vpp, offset
```

## Single parameters

```python
gen.setWaveform(1, "SQUARE")                    # SINE, SQUARE, RAMP, PULSE, NOISE, ARB, DC, PRBS, IQ
gen.setFrequency(1, 2500)                       # Hz (up to 30 MHz on the SDG1032X)
gen.setAmplitude(1, 1.0)                        # Vpp
gen.setOffset(1, 0.5)                           # V
gen.setPhase(1, 90)                             # °
gen.setDuty(1, 10)                              # % (square / pulse)
gen.setLevels(1, 0.0, 5.0)                      # low / high level instead of amplitude + offset
gen.setParam(1, "RISE", 1e-6)                   # any BSWV parameter: SYM, WIDTH, RISE, FALL, DLY, STDEV, MEAN …
gen.getBasic(1)                                 # all of them: {"WVTP": "SINE", "FRQ": 1000.0, "AMP": 4.0, …}
gen.getWaveform(1)                              # "SINE"
gen.getFrequency(1)                             # 1000.0
gen.getAmplitude(1)                             # 4.0
gen.getOffset(1)                                # 0.0
gen.arbList()                                   # built-in arbitrary waves {"M2": "StairUp", …}
```

## Burst, sweep, modulation

```python
gen.burst(1, 5)                                 # 5 cycles per trigger, manual trigger
gen.trigger(1)                                  # fire one burst
gen.burst(1, 10, "INT", period=0.01)            # 10 cycles every 10 ms
gen.burstOff(1)
gen.sweep(1, 100, 10e3, 2.0, mode="LOG")        # 100 Hz → 10 kHz in 2 s, logarithmic
gen.sweepOff(1)
gen.modulate(1, "AM", SRC="INT", MDSP="SINE", FRQ=100, DEPTH=50)   # parameters as in the programming guide
gen.modulationOff(1)
gen.getMode(1)                                  # "BURST", "SWEEP", "MOD" or "" (plain wave)
```

## Raw commands and errors

```python
gen.query("C1:BSWV?")                           # any query → text (an unknown query times out — see errors())
gen.write("C1:BSWV WVTP,SINE")                  # any command
gen.errors()                                    # error queue, [] = no errors
gen.close()                                     # close the connection (the next command opens it again)
```

The module function `parse_params()` turns any `C1:XXXX KEY,VALUE,…` answer into a dict (units dropped).

## Complete example

```python
"""Input filter: 1 kHz passes, 20 kHz is attenuated (generator CH1 → UUT → scope CH1)."""
from instruments.siglent_sdg1032x import SIGLENT_SDG1032X
from instruments.rigol_dho924 import RIGOL_DHO924
from testStrategy import TestStrategy

ts = TestStrategy()
gen = SIGLENT_SDG1032X("192.168.1.73")
scope = RIGOL_DHO924("192.168.1.146")


def steps():
    gen.setLoad(1, "HZ")
    gen.sine(1, 1000, 2.0)
    scope.autoset()
    ts.numericLimitTest("Pass band 1 kHz", scope.getVoltPkPk(1), 1.8, 2.1, "V")
    gen.setFrequency(1, 20e3)
    scope.autoset()
    ts.numericLimitTest("Stop band 20 kHz", scope.getVoltPkPk(1), 0, 0.3, "V")


def finalize():
    gen.allOff()
    gen.close()
    scope.close()


ts.run(steps, finalize)
```
