# Power supply SCPI CTRL 2CH PSU

Driver `testPlatform/psu.py` for the 2-channel power supply controller (MultichannelCerPsu, web page
`http://192.168.1.91/`). Every function below is one line — in the code editor's **?** window hover a line and
press *Insert* or *Copy*. Values are V, A, W; PSU channels are `1` and `2`.

The driver sends raw SCPI over TCP port **8080**, one connection per command. An `ERROR: …` answer or no answer
raises `PsuError`; a wrong argument raises `ValueError`. See [Test platform](test-platform.md) for the test
operators used in the examples.

## Connect

```python
from psu import PSU, PsuError

psu = PSU("192.168.1.91")                       # host, port=8080, timeout=3.0, retries=5
psu.ping()                                      # True if the controller answers
```

Read-only check from a console (switches nothing): `python3 psu.py 192.168.1.91`.

## Output channels

```python
psu.setVoltage(1, 12.0)                         # voltage preset, V
psu.setCurrent(1, 0.5)                          # current limit, A (controller shutdown = limit + 1 A)
psu.on(1)                                       # output on
psu.off(1)                                      # output off, also clears a latched OCP / OVP
psu.setOutput(1, True)                          # on / off from a bool
psu.setup(1, 12.0, 0.5)                         # voltage + limit + output on in one call
psu.setup(2, 5.0, 1.0, on=False)                # preset only, output stays off
psu.allOff()                                    # both outputs off (use it in finalize)
psu.isOn(1)                                     # True / False
```

## Measurements

```python
psu.getVoltage(1)                               # measured output voltage, V (EXT INA228 if present)
psu.getCurrent(1)                               # measured output current, A
psu.getPower(1)                                 # output power, W
psu.waitVoltage(1, 12.0, tolerance=0.1, timeout=5)   # wait until settled, returns the last reading
data = psu.getData()                            # both channels in one request (dict, see below)
data[1]["set_voltage"], data[1]["cv"], data[1]["cc"]  # preset, constant voltage / current mode
data[1]["input_voltage"]                        # input voltage of the PSU module, V
data[1]["temperature"]                          # PSU module temperature, °C
```

`getData()` keys per channel: `voltage`, `voltage_kelvin`, `current`, `temperature`, `set_voltage`, `set_current`,
`power`, `cv`, `cc`, `online` (PSU module connected), `input_voltage`, `soft_ocp`, `ocp_tripped`, `ocp_limit`,
`protect_code`, `current_source`.

In a test:

```python
psu.setup(1, 12.0, 0.5)
ts.numericLimitTest("Supply 12V", psu.waitVoltage(1, 12.0, 0.1, 3), 11.7, 12.3, "V")
ts.numericLimitTest("Idle current", psu.getCurrent(1) * 1000, 35, 50, "mA")
```

## Protection

```python
psu.setOcp(1, 3.0)                              # over-current limit, A
psu.getOcp(1)                                   # 3.0
psu.setSoftOcp(1, True)                         # software OCP on (saved in the controller)
psu.getSoftOcp(1)                               # True / False
psu.isTripped(1)                                # software OCP switched the output off
psu.setOvp(1, 30.0)                             # over-voltage protection, V — set before raising the voltage
psu.protection(1)                               # 'normal', 'OVP', 'OCP', 'OPP', 'OTP', ...
```

A protection as a background check of the test ([watch loop](test-platform.md#watch-loop-emergency-stop-and-other-background-checks)):

```python
watch.require("PSU CH1 OCP", lambda: not psu.isTripped(1), "output tripped by OCP")
```

## PSU module: front panel, display, Kelvin, registers

```python
psu.setRemoteLock(1, True)                      # lock the PSU front panel (output goes off)
psu.getRemoteLock(1)                            # True / False
psu.setBacklight(1, 3)                          # display backlight 0..5
psu.getBacklight(1)                             # 3
psu.setKelvin(1, True)                          # virtual Kelvin: the preset follows the load-side (INA228) voltage
psu.regRead(1, 0, 2)                            # raw Modbus registers from address 0: [1200, 100]
psu.regWrite(1, 0, 1200)                        # write a raw Modbus register (map: SYS Tools of the web page)
psu.regRead(1, 0, 1, slave=1, baud=115200)      # recovery: a PSU with another slave address / baud rate
```

## Onboard DMM (AIN0 … AIN3)

Four channels of the controller's ADS1115; range `0` = 0-5 V, `1` = 0-100 V.

```python
psu.onboardVoltage(0)                           # AIN0, 0-100 V range, V
psu.onboardVoltage(2, 0)                        # AIN2, 0-5 V range (more resolution below 5 V)
psu.onboardRaw(0, 1)                            # (voltage, raw ADC counts)
psu.adcInfo()                                   # 'ADC: ADS1115 16-bit,3xInstances,128SPS,Onboard+2External'
```

```python
ts.numericLimitTest("TP5 voltage", psu.onboardVoltage(1, 1), 11.5, 12.5, "V")
```

## EXT1 / EXT2 measurement modules

An EXT slot holds an **INA228** (voltage, current, power of a channel; 10 mΩ shunt) or an **ADS1115** (voltage,
range 0 = 0-5 V, 1 = 0-100 V).

```python
psu.extType(1)                                  # 'INA228', 'ADS1115' or 'NONE'
psu.extMeasure(1)                               # {'type': 'INA228', 'voltage': 12.01, 'current': 0.09, 'power': 1.07}
psu.extMeasure(2, rng=0)                        # ADS1115: {'type': 'ADS1115', 'voltage': 3.3, 'raw': 17600}
psu.extVoltage(1)                               # V (rng=1 for the ADS1115 0-100 V range)
psu.extCurrent(1)                               # A (INA228)
psu.extPower(1)                                 # W (INA228)
psu.extVI(1)                                    # (voltage, current) from one INA228 read
psu.adcReinit()                                 # detect the modules again after plugging one in
```

```python
v, i = psu.extVI(1)
ts.numericLimitTest("Load voltage", v, 11.8, 12.2, "V")
ts.numericLimitTest("Load current", i, 0.08, 0.12, "A")
```

## EXT_IO cards (TCA9535 relays and inputs)

Up to 8 cards, 16 channels each. Card type: `IN` = 16 inputs, `OUT` = 16 outputs, `MIX` = inputs 0..7 +
outputs 8..15; I²C address 0x20 … 0x27. Cards are numbered from 1 in the order they were added.

```python
psu.ioList()                                    # [{'n': 1, 'type': 'MIX', 'addr': '25', 'name': 'Jig Controller', 'labels': [...]}]
psu.ioIn(1, 0)                                  # input channel 0 of card 1: 0 / 1
psu.ioOut(1, 8, 1)                              # output channel 8 of card 1 on, returns the level read back
psu.ioOut(1, 8, 0)                              # off
psu.ioOutRead(1, 8)                             # actual level of an output (feedback)
psu.ioOutAll(2, 0x00FF)                         # all outputs of card 2 at once (bit = channel), returns the levels
psu.ioState(1)                                  # {'n', 'type', 'addr', 'online', 'pins', 'setpoint'} (bit masks)
psu.ioStates()                                  # the same for every card
psu.ioPin(1, 3)                                 # level of any pin (input or output feedback) from the state
```

Configure the cards (stored in the controller):

```python
psu.ioAdd("OUT", 0x21, "Relays", ["K1", "K2", "K3"])   # returns the new card number
psu.ioAdd("MIX", "25", "Jig Controller")               # address as int or hex string
psu.ioEdit(1, "OUT", 0x21, "Relays A", ["K1", "K2"])   # changing type / address resets the outputs
psu.ioDelete(2)                                        # following cards are renumbered
psu.ioClear()                                          # delete all cards (outputs off)
```

Relays in a test — always switch them off in `finalize()`:

```python
def steps():
    psu.ioOut(1, 8, 1)                          # K1: connect the load
    ts.booleanTest("Load relay K1 closed", psu.ioOutRead(1, 8) == 1, True)
    ts.booleanTest("Lid switch closed", psu.ioIn(1, 0) == 0, True)


def finalize():
    psu.ioOutAll(1, 0x0000)                     # all relays of card 1 off
    psu.allOff()
```

## External I²C bus

The controller's own I²C connector (0x08 … 0x77); up to 32 bytes per transfer.

```python
psu.i2cScan()                                   # [0x25, 0x40, 0x41]
psu.i2cRead(0x41, 0x00, 2)                      # 2 bytes from register 0x00: [0xC3, 0x40]
psu.i2cWrite(0x41, 0x01, [0xC3, 0x83])          # write bytes to register 0x01
```

> [!WARNING]
> `i2cScan()` probes every address — some chips do not like it. Scan only a bus you know.

## Calibration (service)

Normally done on the **SYS Tools** page of the PSU; listed here for automated calibration jigs.

```python
psu.onboardCalData()                            # [{'ch': 0, 'range': 0, 'factor': 0.000197, 'zero': 791}, ...]
psu.getRefVoltage()                             # reference voltage of the onboard calibration, V
psu.setRefVoltage(5.109)                        # 2.0 … 5.999 V
psu.setCalSource(True)                          # internal calibration reference on / off
psu.onboardCalibrate(0, 1)                      # AIN0, 0-100 V against the reference (inputs disconnected!)
psu.setOnboardFactor(0, 1, 0.0031305)           # set a coefficient by hand
psu.clearOnboardCal()                           # all coefficients 1.0, zeros 0
psu.extCalData(1)                               # {'gain0', 'zero0', 'gain1', 'zero1'} of an EXT ADS1115
psu.extCalZero(1, 1)                            # step 1: input shorted, store the zero of range 1
psu.extCalibrate(1, 1, 24.000)                  # step 2: known voltage applied, value of the reference meter
psu.extCalibrateWithPsu(1, 1)                   # EXT ADS1115 of channel 1 with its own PSU as the source
```

> [!CAUTION]
> Calibration commands overwrite the constants in the controller's flash. Read `onboardCalData()` /
> `extCalData()` first and keep the values.

## Device, software version, event log

```python
psu.firmwareVersion()                           # '2.90'
psu.hwVersion()                                 # '1.0.0'
psu.identify()                                  # *IDN?: model, version, build date, serial (text)
psu.deviceId()                                  # ('MultichannelCerPsu', '0001')
psu.deviceInfo()                                # {'ip', 'mac', 'ports', 'firmware', 'uptime_s', 'status'}
psu.isReady()                                   # status READY (not FAULT)
psu.resetCause()                                # 'power-on', 'watchdog', ...
psu.logInfo()                                   # {'entries': 64, 'lost': 0, 'capacity': 512}
psu.log(10)                                     # newest 10 events: [{'seq', 'event': 'Boot', 'src', 'value', ...}]
psu.clearLog()                                  # clear the event log
psu.inventory()                                 # full text report: model, network, calibration, modules, log
```

Record the instrument in the test log:

```python
ts.logResult("PSU firmware", psu.isReady(), psu.firmwareVersion())
```

## Any SCPI command

```python
psu.query("VOLT:1?")                            # answer text, e.g. '12.02'
psu.command("OUT:1:0")                          # setting command; ERROR answers raise PsuError
```

The full command list is on the *SCPI Commands* page of the PSU web interface.

## Complete example

```python
"""Board: power-up through the PSU, load relay on EXT_IO, current check."""
from psu import PSU
from testStrategy import TestStrategy
from testWatch import TestWatch

ts = TestStrategy()
psu = PSU("192.168.1.91")
watch = TestWatch().require("PSU CH1 OCP", lambda: not psu.isTripped(1), "output tripped by OCP", interval=0.5)


def steps():
    ts.logResult("PSU ready", psu.isReady(), psu.firmwareVersion())
    psu.setOvp(1, 15.0)
    psu.setup(1, 12.0, 0.5)
    ts.numericLimitTest("Supply 12V", psu.waitVoltage(1, 12.0, 0.1, 3), 11.7, 12.3, "V")
    psu.ioOut(1, 8, 1)                          # K1: load on
    ts.numericLimitTest("Load current", psu.extCurrent(1), 0.08, 0.12, "A")


def finalize():
    psu.ioOutAll(1, 0x0000)
    psu.allOff()


if __name__ == "__main__":
    ts.run(steps, finalize, watch=watch)
```
