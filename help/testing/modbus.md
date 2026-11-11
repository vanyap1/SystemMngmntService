# Modbus master (low level)

Driver `testPlatform/instruments/modbus.py`: Modbus requests from a test script, the same level as the HW Utils
**Modbus** monitor — function codes, addresses and raw register values. What a register means (scaling, units,
bit fields) is up to the script; a device-specific driver can be built on top of it later. One line per function:
in the code editor's **?** window hover a line and press *Insert* or *Copy*.

Find the right unit id, addresses and formats in HW Utils → Modbus first, then copy them here.

## Connect

```python
from instruments.modbus import ModbusRTU, ModbusTCP, ModbusUDP, ModbusRTUoverTCP, ModbusRTUoverUDP
from instruments.modbus import ModbusError, ModbusException

mb = ModbusRTU("/dev/ttyUSB0", 115200, unit=1)  # serial: parity="N", bytesize=8, stopbits=1, timeout=0.5, retries=0
mb = ModbusTCP("192.168.1.50")                  # Modbus TCP: port=502, unit=1, timeout=1.0, retries=0
mb = ModbusUDP("192.168.1.50")                  # Modbus TCP frames over UDP
mb = ModbusRTUoverTCP("192.168.1.60", 4001)     # RTU frames through a serial-to-Ethernet gateway
mb = ModbusRTUoverUDP("192.168.1.60", 4001)
```

The serial port is opened by the first request and stays open (exclusive — the HW Utils tools cannot take it
meanwhile) until `close()`; sockets reconnect by themselves when the device closed them. Serial requests keep
the Modbus silent interval (3.5 characters) between frames.

Read-only check from a console (in `testPlatform/`): `python3 instruments/modbus.py /dev/ttyUSB0 115200 1 0 10` —
port, baud, unit, first address, count; reads holding registers (function 03).

## Read

```python
mb.readHolding(0, 12)                           # 03 holding registers → [0..65535] × 12
mb.readInput(0, 4)                              # 04 input registers
mb.readCoils(0, 16)                             # 01 coils → [0/1] × 16
mb.readDiscrete(0, 8)                           # 02 discrete inputs → [0/1]
mb.readHolding(0, 2, unit=5)                    # every function takes unit= for another device on the line
```

## Write

```python
mb.writeRegister(20, 1500)                      # 06 one register (negative = two's complement)
mb.writeRegisters(20, [1500, 2, 0])             # 16 several registers
mb.writeCoil(3, 1)                              # 05 one coil
mb.writeCoils(8, [1, 0, 1, 1])                  # 15 several coils
mb.writeRegister(20, 0, unit=0)                 # unit 0 = broadcast: every device, no answer (RTU)
```

## Raw request, scan, trace

```python
mb.request(3, bytes([0, 0, 0, 2]))              # any function: data after the function code → answer data (bytes)
mb.scan(1, 20, timeout=0.1)                     # unit ids that answer a read of register 0: [1, 7]
mb.last                                         # last request: {"tx": "01 03 00 00 00 0C 45 CF", "rx": "01 03 18 …", "ms": 27.5}
mb.close()                                      # free the port / socket — in finalize()
```

## Register formats

Registers arrive as unsigned 16-bit numbers. Module functions turn them into other types (like the monitor's
format column); `swap=True` = low word first.

```python
from instruments.modbus import to_s16, to_u32, to_s32, to_float32, to_ascii, from_u32, from_float32

to_s16([65535])                                 # [-1]
to_u32([1, 2])                                  # [65538]; to_u32(regs, swap=True) for low word first
to_s32([65535, 65531])                          # [-5]
to_float32([0x3FC0, 0])                         # [1.5]
to_ascii([0x332E, 0x3437])                      # "3.47" (2 characters per register; swap_bytes=True if reversed)
from_float32(1.5)                               # [0x3FC0, 0] — for writeRegisters
from_u32(70000)                                 # [1, 4464]
```

## Errors

* `ModbusException` — the device answered with an exception; `e.code`: 1 illegal function, 2 illegal data
  address, 3 illegal data value, 4 device failure, 6 busy.
* `ModbusError` — no answer (timeout), CRC error, an answer from another unit, port / host cannot be opened.
  `retries=2` repeats a request after a timeout or a CRC error (noisy RS-485 lines); an exception answer is never
  repeated.

Both stop the step with an ERROR row unless you catch them.

## Complete example

```python
"""Charger over RS-485: firmware and model registers, a status register in range."""
from instruments.modbus import ModbusRTU, to_ascii
from testStrategy import TestStrategy

ts = TestStrategy()
mb = ModbusRTU("/dev/ttyUSB0", 115200, unit=1, retries=1)


def steps():
    regs = mb.readHolding(0, 12)
    ts.stringMatchTest("Firmware", to_ascii(regs[4:6]), "3.47")
    ts.stringMatchTest("Model", to_ascii(regs[7:11]).strip(), "J1772_0")
    ts.numericLimitTest("State", regs[2], 0, 9, "")


def finalize():
    mb.close()


ts.run(steps, finalize)
```
