"""Instrument drivers of the test platform (import them from a test script in testPlatform/):

    from instruments.psu import PSU                 # 2-channel SCPI power supply (TCP)
    from instruments.dmm import FS9922DMM           # FS9922 multimeter (USB serial)
    from instruments.dmm2 import FS9922DMM          # FS9922 multimeter, simple reader
    from instruments.adc import ADC                 # ADC on I2C (smbus2)
    from instruments.stm8_flash import STM8Flasher  # stm8flash / ST-Link programmer
    from instruments.uut_serial import UUTSerial    # UART link to the unit under test

Firmware images and other binaries live in instruments/fw/ — use FW_DIR / fw_path() so a script finds them
whatever its working directory is:

    from instruments import FW_DIR, fw_path
    flasher = STM8Flasher()                         # uses FW_DIR by default
    open(fw_path("eTest.bin"), "rb")

The test framework itself (testStrategy.py, testWatch.py) stays in testPlatform/.
"""
import os

FW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fw")


def fw_path(name: str) -> str:
    """Absolute path of a file in instruments/fw/."""
    return os.path.join(FW_DIR, name)
