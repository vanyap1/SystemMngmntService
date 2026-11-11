# Instruments — drivers for test scripts

Every instrument of a station is a Python object created once at the top of a test script: you pass the
address (IP, serial port, file) and then call its functions in the steps. All drivers live in
`testPlatform/instruments/` and are imported the same way:

```python
from instruments.psu_custom6020 import PSU_CUSTOM6020
from instruments.rigol_dho924 import RIGOL_DHO924
from instruments.owon_xdm import OWON_XDM
from instruments.ssh_term import SshTerm
```

**File name = the instrument** (maker + model or series, lower case), **class name = the same in capitals**: a script
shows at a glance what it connects to, and two models never share a name. Protocols and tools that are not one
instrument (Modbus, SCPI base, terminals, files) keep a generic name. A new model of a known family is one more
small file — see `rigol_dho804.py` / `rigol_dho924.py` on top of the common `rigol_dho.py`.

## Available drivers

### Instruments

| File | Class | Instrument | Create it | Page |
|---|---|---|---|---|
| `psu_custom6020.py` | `PSU_CUSTOM6020` | custom 2-channel SCPI power supply, 60 V / 20 A (TCP :8080) | `psu = PSU_CUSTOM6020("192.168.1.91")` | [PSU_CUSTOM6020](psu-custom6020.md) |
| `psu_custom305.py` | `PSU_CUSTOM305` | custom 1-channel Ethernet PSU controller, 30 V / 5 A (TCP :8080) | `psu = PSU_CUSTOM305("192.168.1.99")` | [PSU_CUSTOM305](psu-custom305.md) |
| `rigol_dho924.py` | `RIGOL_DHO924` | Rigol DHO924 oscilloscope, 4 ch, 250 MHz (LXI :5555) | `scope = RIGOL_DHO924("192.168.1.146")` | [Rigol DHO](rigol-dho.md) |
| `rigol_dho804.py` | `RIGOL_DHO804` | Rigol DHO804 oscilloscope, 4 ch, 70 MHz (LXI :5555) | `scope = RIGOL_DHO804("192.168.1.147")` | [Rigol DHO](rigol-dho.md) |
| `owon_xdm.py` | `OWON_XDM` | OWON XDM series bench multimeter (USB or LAN) | `dmm = OWON_XDM(serial="/dev/ttyUSB0")` | [OWON XDM](owon-xdm.md) |
| `owon_oel.py` | `OWON_OEL` | OWON OEL series electronic load (USB or LAN) | `load = OWON_OEL(serial="/dev/ttyUSB1")` | [OWON OEL](owon-oel.md) |
| `fs9922.py` | `FS9922DMM` | FS9922 handheld multimeter, background reader (USB serial) | `FS9922DMM("/dev/ttyUSB0")` | `instruments/fs9922.py` |
| `fs9922_bridge.py` | `FS9922DMM` | FS9922-DMM4 through the STM8 ASCII bridge | `FS9922DMM("/dev/ttyUSB0")` | `instruments/fs9922_bridge.py` |
| `ads1115.py` | `ADC` | ADS1115 ADC on I²C | `ADC()` | `instruments/ads1115.py` |
| `stlink_stm8.py` | `STM8Flasher` | ST-Link + stm8flash programmer | `STM8Flasher(chip="STM8S003F3")` | [Test platform](test-platform.md) |

### Protocols and tools

| File | Class | What | Create it | Page |
|---|---|---|---|---|
| `modbus.py` | `ModbusRTU`, `ModbusTCP` … | Modbus master, low level (RTU, TCP, UDP, RTU over TCP / UDP) | `mb = ModbusRTU("/dev/ttyUSB0", 115200)` | [Modbus](modbus.md) |
| `serial_term.py` | `SerialTerm` | text console on a UART (UUT, modem, bootloader) | `uut = SerialTerm("/dev/ttyS1", 115200)` | [Serial terminal](serial-term.md) |
| `ssh_term.py` | `SshTerm` | SSH to the UUT or any Linux box | `uut = SshTerm("192.168.1.80", "root", "pw")` | [SSH terminal](ssh-term.md) |
| `param_file.py` | `ParamFile` | parameters by key in a file (calibration, counters) | `cal = ParamFile(data_path("cal.ini"))` | [Parameter files](param-file.md) |
| `uut_serial.py` | `UUTSerial` | binary UART link to the UUT | `UUTSerial("/dev/ttyS1", 9600)` | `instruments/uut_serial.py` |
| `scpi.py` | `ScpiInstrument` | base of SCPI drivers (LAN or serial) | see below | this page |
| `rigol_dho.py` | `RigolScope` | common part of the Rigol DHO800 / DHO900 drivers | — | [Rigol DHO](rigol-dho.md) |
| `psu_tcp.py` | `OneShotTcpPsu` | transport of the custom PSU controllers | — | — |

## How to create a device

1. **Create it once, at the top of the script**, with the station's address. Creating does not connect yet —
   the first command does, so a missing instrument fails in the step that needs it (an ERROR row), not at import.
2. **Use it in `steps()`**, feed every value to a test operator (`numericLimitTest`, `logResult` …). A value the
   instrument cannot measure (scope without a signal, overload) is `None` — `numericLimitTest` turns it into an
   ERROR row, so you never compare against a random number.
3. **Bring it to a safe state in `finalize()`** — outputs off, load off, terminals closed. `finalize` runs after a
   pass, a fail with stop-on-fail, an exception and the Stop button.
4. **Errors**: every driver raises its own exception (`InstrumentError`, `TermError`, `SshError`, `ParamError`,
   `PsuError`, `ModbusError`) with a readable message. You do not need to catch it — the test engine logs it as an ERROR row and
   runs `finalize`.

Addresses that differ between stations (IP of the scope, serial port names) are best kept in a parameter file of
the station, so the same script runs everywhere:

```python
station = ParamFile(data_path("station.ini"))
station.create({"scope_ip": "192.168.1.146", "dmm_port": "/dev/ttyUSB0", "uut_ip": "192.168.1.80"})
scope = RIGOL_DHO924(station.get("scope_ip"))
```

## A complete test script

```python
"""Power board end-of-line test: supply, 5 V rail ripple, load regulation, firmware version over SSH."""
from testStrategy import TestStrategy
from instruments.psu_custom6020 import PSU_CUSTOM6020
from instruments.rigol_dho924 import RIGOL_DHO924
from instruments.owon_xdm import OWON_XDM
from instruments.owon_oel import OWON_OEL
from instruments.ssh_term import SshTerm
from instruments.param_file import ParamFile, data_path

ts = TestStrategy()
psu = PSU_CUSTOM6020("192.168.1.91")
scope = RIGOL_DHO924("192.168.1.146")
dmm = OWON_XDM(serial="/dev/ttyUSB0")
load = OWON_OEL(serial="/dev/ttyUSB1")
uut = SshTerm("192.168.1.80", "root", "root")
stats = ParamFile(data_path("counters.json"))


def steps():
    ts.section("Power")
    psu.setup(1, 12.0, 2.0)
    ts.numericLimitTest("Input 12V", psu.waitVoltage(1, 12.0), 11.7, 12.3, "V")
    ts.numericLimitTest("Rail 5V", dmm.getVoltDC(), 4.9, 5.1, "V")

    ts.section("Ripple and load")
    scope.setScale(1, 0.02)
    ts.numericLimitTest("Ripple 5V", scope.getVoltPkPk(1) * 1000, 0, 50, "mV")
    load.setup("CC", 1.0)
    load.waitCurrent(1.0)
    ts.numericLimitTest("Rail 5V at 1 A", dmm.getVoltDC(), 4.85, 5.1, "V")

    ts.section("Firmware")
    uut.waitOnline(60)
    ts.stringMatchTest("Firmware version", uut.cmd("cat /etc/fw_version"), "2.4.1")
    stats.increment("boards_tested")


def finalize():
    load.off()
    psu.allOff()
    dmm.local()
    uut.close()


ts.run(steps, finalize)
```

## Checking an instrument from a console

Every driver can be tried in the code editor's terminal (in `testPlatform/`) before it goes into a test:

```python
python3 -c "from instruments.rigol_dho924 import RIGOL_DHO924; s = RIGOL_DHO924('192.168.1.146'); print(s.idn(), s.getVoltPkPk(1))"
python3 instruments/rigol_dho.py 192.168.1.146          # read-only check: identity and a few measurements
python3 instruments/psu_custom6020.py 192.168.1.91             # read-only check of the power supply
python3 instruments/psu_custom305.py 192.168.1.99   # the same for PSU_CUSTOM305
python3 instruments/modbus.py /dev/ttyUSB0 115200 1 0 10   # read 10 holding registers of unit 1 (function 03)
```

The HW Utils **Terminal** and **Modbus** tools are handy to find the right commands interactively first.

## Writing a driver for another SCPI instrument

Most bench instruments (power supplies, loads, meters, generators, scopes) speak SCPI over LAN or USB-serial.
`instruments/scpi.py` does the transport, the line ends, timeouts, reconnects and binary blocks — a new driver
only names its commands:

```python
from instruments.scpi import ScpiInstrument


class MyGenerator(ScpiInstrument):
    DEFAULT_PORT = 5025                        # raw SCPI socket of the instrument

    def setFrequency(self, ch, hz):
        self.write(f":SOUR{ch}:FREQ {hz}")

    def getFrequency(self, ch):
        return self.queryFloat(f":SOUR{ch}:FREQ?")


gen = MyGenerator(host="192.168.1.70")          # or MyGenerator(serial="/dev/ttyUSB2", baud=9600)
gen.idn()
```

The base gives every SCPI driver these functions too:

```python
scope.idn()                                     # *IDN? — "maker,model,serial,firmware"
scope.ping()                                    # True if the instrument answers
scope.reset()                                   # *RST — factory defaults
scope.clearStatus()                             # *CLS
scope.waitDone(10)                              # *OPC? — wait until the last commands finished
scope.errors()                                  # error queue, [] = no errors
scope.write(":RUN")                             # any command without an answer
scope.query(":TRIGger:STATus?")                 # any query → text
scope.queryFloat(":ACQuire:SRATe?")             # any query → float (None = "no valid value")
scope.queryBlock(":DISPlay:DATA? PNG")          # binary block → bytes
scope.close()                                   # close the connection (the next command opens it again)
```

Put the new file into `testPlatform/instruments/`, add a page next to this one describing every function, and
the code editor's **?** window shows it to everybody writing tests.
