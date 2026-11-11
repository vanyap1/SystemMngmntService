# Serial terminal — command and answer over a UART

Driver `testPlatform/instruments/serial_term.py`: a text console on a serial port — the UUT's debug UART, an AT
modem, a bootloader, any device that answers text commands. Send a command, get its answer as a string.
For binary protocols use `instruments/uut_serial.py` (`UUTSerial`). See [Instruments](instruments.md).

## Connect

```python
from instruments.serial_term import SerialTerm, TermError

uut = SerialTerm("/dev/ttyS1", 115200)          # eol="\r\n", timeout=2.0, idle=0.2, prompt=None
uut = SerialTerm("/dev/ttyUSB0", 9600, eol="\r", prompt="uut> ")
uut.open()                                      # optional: the first command opens the port
uut.close()                                     # in finalize()
```

An answer ends at the first of: the `until` text, the `prompt`, `idle` seconds of silence after the last byte,
`timeout`. The echo of the command and the prompt are removed.

## Commands

```python
uut.cmd("VERSION?")                             # answer text, e.g. "fw 1.2.3"
uut.cmd("AT", until="OK")                       # wait for a word — TermError if it does not come
uut.cmd("SELFTEST", until="DONE", timeout=20)   # long command
uut.lines("STATUS")                             # answer split into lines
uut.value("TEMP?")                              # first number in the answer → 23.5 (None if none)
uut.value("ADC?", r"ch2=(\d+)")                 # the number of a regex group
```

```python
ts.stringMatchTest("Firmware", uut.cmd("VERSION?"), "fw 1.2.3")
ts.numericLimitTest("Board temperature", uut.value("TEMP?"), 10, 60, "°C")
```

## Waiting and raw access

```python
uut.expect("login:", timeout=30)                # wait for a text / regex (boot prompt)
uut.write("root")                               # send a line without waiting for the answer
uut.read(idle=0.5)                              # collect what arrives until 0.5 s of silence
uut.flush()                                     # drop old output, returns it
uut.log                                         # [("tx", text), ("rx", text)] of this session
```

```python
uut.expect("login:", timeout=60)
uut.write("root")
uut.expect("Password:")
uut.write("root")
uut.expect("# ")
```
