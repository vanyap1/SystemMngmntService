"""Instrument drivers of the test platform (import them from a test script in testPlatform/):

File = instrument (maker + model / series), class = the same name in capitals:

    from instruments.psu_custom6020 import PSU_CUSTOM6020    # custom 2-channel SCPI power supply 60 V / 20 A (TCP :8080)
    from instruments.psu_custom305 import PSU_CUSTOM305      # custom 1-channel Ethernet PSU controller 30 V / 5 A
    from instruments.rigol_dho924 import RIGOL_DHO924        # Rigol DHO924 oscilloscope (LXI :5555)
    from instruments.rigol_dho804 import RIGOL_DHO804        # Rigol DHO804 oscilloscope (LXI :5555)
    from instruments.owon_xdm import OWON_XDM                # OWON XDM bench multimeter (USB serial / LAN)
    from instruments.owon_oel import OWON_OEL                # OWON OEL electronic load (USB serial / LAN)
    from instruments.fs9922 import FS9922DMM                 # FS9922 multimeter, background reader (USB serial)
    from instruments.fs9922_bridge import FS9922DMM          # FS9922-DMM4 through the STM8 ASCII bridge
    from instruments.ads1115 import ADC                      # ADS1115 ADC on I2C (smbus2)
    from instruments.stlink_stm8 import STM8Flasher          # ST-Link + stm8flash programmer

Protocols and tools (not one instrument):

    from instruments.modbus import ModbusRTU                 # Modbus master, low level (also ModbusTCP / UDP / RTUoverTCP)
    from instruments.serial_term import SerialTerm           # text command / answer on a UART
    from instruments.ssh_term import SshTerm                 # commands / files on a Linux host over SSH
    from instruments.param_file import ParamFile, data_path  # parameters by key in a file (testPlatform/data/)
    from instruments.uut_serial import UUTSerial             # UART link to the unit under test
    from instruments.scpi import ScpiInstrument              # base for new SCPI drivers (LAN or serial)

Firmware images and other binaries live in instruments/fw/ — use FW_DIR / fw_path() so a script finds them
whatever its working directory is:

    from instruments import FW_DIR, fw_path
    flasher = STM8Flasher()                         # uses FW_DIR by default
    open(fw_path("eTest.bin"), "rb")

How to create devices and every function: help/testing/instruments.md (Docs page → testing → Instruments).
The test framework itself (testStrategy.py, testWatch.py) stays in testPlatform/.
"""
import os

FW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fw")


def fw_path(name: str) -> str:
    """Absolute path of a file in instruments/fw/."""
    return os.path.join(FW_DIR, name)
