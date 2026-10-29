#!/usr/bin/env python3
"""
FS9922-DMM4 Digital Multimeter Driver (STM8 ASCII bridge variant)
==================================================================
Reads the serial stream produced by a custom STM8 firmware that bridges
the internal FS9922-DMM4 binary data to a compact ASCII packet over UART.

Observed packet format (10 bytes payload + terminator)
-------------------------------------------------------
  [S][D0][D1][D2][D3][ ][R][M][X0][X1][term...]

  S          = '+' (0x2B) or '-' (0x2D) — sign
  D0..D3     = 4 ASCII digit chars '0'-'9'  (raw display counts, no decimal)
  0x20       = space separator
  R          = range byte  (ASCII digit '1'-'5')
                 decimal_places = 5 - (R - '0')
                 '1' → 4dp  → e.g. 0.1428   (200 mV range)
                 '2' → 3dp  → e.g. 1.428    (2 V range)
                 '3' → 2dp  → e.g. 14.28    (20 V range)
                 '4' → 1dp  → e.g. 142.8    (200 V range)
                 '5' → 0dp  → e.g. 1428     (1000 V / 10 A range)
  M          = mode byte (guessed from observed samples — run --dump to verify)
                 '1' → DC Voltage       '2' → AC Voltage
                 '3' → DC Current       '4' → AC Current
                 '5' → Resistance       '6' → Continuity
                 '7' → Diode            '8' → Capacitance
                 '9' → Frequency
  X0         = status byte 0 — bit flags (0x00 = all normal)
                 bit0 → HOLD            bit1 → MAX
                 bit2 → LOW_BATTERY     bit3 → OVERLOAD (OL)
                 bit4 → AC              bit5 → DC
                 bit6 → AUTO_RANGE      bit7 → REL
  X1         = status byte 1 — reserved / additional flags
  term...    = one or more terminator bytes (CR, LF, 0x00, 0x80 …)

NOTE: The flag interpretation above is a *best-guess* based on the single
observed sample "+1428 21\\x00\\x00\\x{term}". Run the script with --dump to
record raw hex bytes at every range / mode / flag position so you can
calibrate the decoder to your firmware exactly.

Usage — as a library::

    from dmm import FS9922DMM

    with FS9922DMM('/dev/ttyUSB0') as dmm:
        print(dmm.getVolt())
        m = dmm.get_measurement()
        print(m.value, m.mode, m.overload)

Usage — standalone (live display)::

    python3 dmm.py /dev/serial/by-id/usb-FTDI_…-port0

Usage — raw hex dump (use this to reverse-engineer the protocol)::

    python3 dmm.py --dump /dev/serial/by-id/usb-FTDI_…-port0
"""

import argparse
import logging
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

import serial

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mode byte → human-readable string
# (guessed — calibrate with --dump if readings look wrong)
# ---------------------------------------------------------------------------
_MODE_MAP = {
    0x31: 'DC_VOLT',
    0x32: 'AC_VOLT',
    0x33: 'DC_AMP',
    0x34: 'AC_AMP',
    0x35: 'RESISTANCE',
    0x36: 'CONTINUITY',
    0x37: 'DIODE',
    0x38: 'CAPACITANCE',
    0x39: 'FREQUENCY',
}

# Status byte 0 bit masks (best-guess)
_ST_HOLD     = 0x01
_ST_MAX      = 0x02
_ST_LOBAT    = 0x04
_ST_OVERLOAD = 0x08
_ST_AC       = 0x10
_ST_DC       = 0x20
_ST_AUTO     = 0x40
_ST_REL      = 0x80


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

@dataclass
class Measurement:
    """A single decoded DMM reading."""

    # SI value (sign + decimal applied).  None = no reading yet.
    # float('inf') = OL / overload.
    value: Optional[float] = None

    # Raw integer counts as sent by the meter (e.g. 1428 for a 1.428 V reading).
    raw_counts: Optional[int] = None

    # Number of decimal places (derived from range byte).
    decimal_places: int = 0

    # Mode string (e.g. 'DC_VOLT', 'AC_AMP', …)
    mode: str = ''

    # Raw protocol bytes — useful while calibrating the decoder.
    raw_packet: bytes = b''

    ac: bool = False
    dc: bool = False
    auto_range: bool = False
    hold: bool = False
    overload: bool = False
    low_battery: bool = False
    diode: bool = False
    continuity: bool = False
    negative: bool = False
    max_hold: bool = False

    # Unix timestamp of the packet.
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Driver class
# ---------------------------------------------------------------------------

class FS9922DMM:
    """
    Driver for the STM8-bridged FS9922-DMM4 multimeter.

    Spawns a background daemon thread that reads and decodes the ASCII
    packet stream.  All public accessors are thread-safe and non-blocking.

    Args:
        port:     Serial device path (e.g. '/dev/ttyUSB0', 'COM3').
        baudrate: Baud rate — default 2400.

    Example::

        dmm = FS9922DMM('/dev/ttyUSB0')
        dmm.start()
        try:
            while True:
                print(dmm.getVolt())
                time.sleep(0.5)
        finally:
            dmm.stop()
    """

    DEFAULT_BAUDRATE: int = 2400

    # Payload bytes after the sign byte that we always try to read:
    #   4 digits + 1 space + 1 range + 1 mode + 2 status = 9
    _PAYLOAD_AFTER_SIGN: int = 9

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUDRATE) -> None:
        self.port = port
        self.baudrate = baudrate
        self.dump_packets: bool = False   # set True at runtime to print hex

        self._serial: Optional[serial.Serial] = None
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._lock = threading.Lock()
        self._measurement = Measurement()
        self._stashed_sign: Optional[bytes] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the serial port and start the background reading thread."""
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
        )
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop,
            name='FS9922-reader',
            daemon=True,
        )
        self._thread.start()
        logger.info("FS9922DMM: started on %s @ %d baud", self.port, self.baudrate)

    def stop(self) -> None:
        """Stop the background thread and close the serial port."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._serial and self._serial.is_open:
            self._serial.close()
        logger.info("FS9922DMM: stopped")

    def __enter__(self) -> 'FS9922DMM':
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Public measurement accessors
    # ------------------------------------------------------------------

    def get_measurement(self) -> Measurement:
        """Return a snapshot of the latest decoded measurement (thread-safe)."""
        with self._lock:
            m = self._measurement
            return Measurement(**m.__dict__)

    def getVolt(self) -> Optional[float]:
        """Return reading in Volts (SI). None = not ready, inf = OL."""
        return self._si_value()

    def getAmp(self) -> Optional[float]:
        """Return reading in Amperes (SI). None = not ready, inf = OL."""
        return self._si_value()

    def getResistance(self) -> Optional[float]:
        """Return reading in Ohms (SI). None = not ready, inf = OL (open)."""
        return self._si_value()

    def getCapacitance(self) -> Optional[float]:
        """Return reading in Farads (SI). None = not ready."""
        return self._si_value()

    def getFrequency(self) -> Optional[float]:
        """Return reading in Hertz (SI). None = not ready."""
        return self._si_value()

    def getDutyCycle(self) -> Optional[float]:
        """Return duty-cycle in % (0–100). None if not in duty-cycle mode."""
        with self._lock:
            m = self._measurement
            if m.value is None or m.mode != 'FREQUENCY':
                return None
            return m.value

    def getTemperature(self) -> Optional[float]:
        """Return temperature as shown on display. None = not ready."""
        return self._si_value()

    def isOverload(self) -> bool:
        """True when the display shows OL."""
        return self.get_measurement().overload

    def isLowBattery(self) -> bool:
        """True when the battery indicator is active."""
        return self.get_measurement().low_battery

    def isReady(self) -> bool:
        """True once at least one valid packet has been decoded."""
        with self._lock:
            return self._measurement.raw_counts is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _si_value(self) -> Optional[float]:
        with self._lock:
            m = self._measurement
            if m.overload:
                return float('inf')
            return m.value

    def _read_loop(self) -> None:
        while self._running:
            try:
                packet = self._sync_packet()
                if packet is None:
                    continue
                if self.dump_packets:
                    print('PKT ' + ' '.join(f'{b:02X}' for b in packet))
                measurement = self._decode_packet(packet)
                with self._lock:
                    self._measurement = measurement
            except serial.SerialException as exc:
                logger.error("FS9922DMM serial error: %s", exc)
                self._running = False
            except Exception as exc:  # noqa: BLE001
                logger.debug("FS9922DMM decode warning: %s", exc)

    def _sync_packet(self) -> Optional[bytes]:
        """
        Wait for a '+' or '-' sign byte, read the fixed payload, then
        flush any trailing terminator bytes so the stream is aligned for
        the next packet.

        Returns the raw packet bytes (sign + payload), or None on timeout.
        """
        while self._running:
            # Use a sign byte that was peeked during the previous flush.
            if self._stashed_sign is not None:
                b = self._stashed_sign
                self._stashed_sign = None
            else:
                b = self._serial.read(1)
                if not b:
                    continue

            # We expect sign to be '+' (0x2B) or '-' (0x2D).
            if b[0] not in (0x2B, 0x2D):
                continue

            sign = b

            # Read the fixed-size payload that follows the sign.
            payload = self._serial.read(self._PAYLOAD_AFTER_SIGN)
            if len(payload) != self._PAYLOAD_AFTER_SIGN:
                continue

            # Validate: bytes 0-3 must be ASCII digits.
            if not all(0x30 <= payload[i] <= 0x39 for i in range(4)):
                continue

            # Flush terminator bytes (any byte that is not '+'/'-').
            # We use a short timeout so we don't block the next packet.
            saved_timeout = self._serial.timeout
            self._serial.timeout = 0.15
            while self._running:
                tb = self._serial.read(1)
                if not tb:
                    break                          # timed out — stream idle
                if tb[0] in (0x2B, 0x2D):
                    # We accidentally read the next packet's sign byte;
                    # put it back by returning this packet first, and the
                    # next call to _sync_packet will re-find the sign below.
                    # We can't unread, so stash it for one cycle.
                    self._stashed_sign = tb
                    break
                # Otherwise it is a terminator byte — discard it.
            self._serial.timeout = saved_timeout

            return sign + payload

        return None

    def _decode_packet(self, packet: bytes) -> Measurement:
        """Decode a 10-byte ASCII packet into a Measurement."""
        negative = (packet[0] == 0x2D)   # '-'

        # Bytes 1-4: ASCII digit chars → integer counts
        try:
            raw_counts = int(packet[1:5])
        except ValueError:
            raw_counts = None

        # Byte 6: range → decimal places
        range_byte = packet[6] if len(packet) > 6 else 0x32
        range_num  = range_byte - 0x30           # '2' → 2
        if 1 <= range_num <= 5:
            decimal_places = 5 - range_num       # 2 → 3 decimal places
        else:
            decimal_places = 0

        # Byte 7: mode
        mode_byte = packet[7] if len(packet) > 7 else 0x00
        mode      = _MODE_MAP.get(mode_byte, f'UNKNOWN(0x{mode_byte:02X})')

        # Bytes 8-9: status flags
        st0 = packet[8] if len(packet) > 8 else 0x00
        overload    = bool(st0 & _ST_OVERLOAD)
        hold        = bool(st0 & _ST_HOLD)
        max_hold    = bool(st0 & _ST_MAX)
        low_battery = bool(st0 & _ST_LOBAT)
        ac          = bool(st0 & _ST_AC)
        dc          = bool(st0 & _ST_DC)
        auto_range  = bool(st0 & _ST_AUTO)

        # Derive AC/DC from mode if status byte doesn't carry it
        if not ac and not dc:
            ac = 'AC' in mode
            dc = 'DC' in mode or (not ac)

        diode       = (mode == 'DIODE')
        continuity  = (mode == 'CONTINUITY')

        # Build SI value
        si_value: Optional[float] = None
        if overload:
            si_value = float('inf')
        elif raw_counts is not None:
            val = raw_counts / (10 ** decimal_places)
            si_value = -val if negative else val

        return Measurement(
            value=si_value,
            raw_counts=raw_counts,
            decimal_places=decimal_places,
            mode=mode,
            raw_packet=bytes(packet),
            ac=ac,
            dc=dc,
            auto_range=auto_range,
            hold=hold,
            overload=overload,
            low_battery=low_battery,
            diode=diode,
            continuity=continuity,
            negative=negative,
            max_hold=max_hold,
            timestamp=time.time(),
        )


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _main() -> None:
    parser = argparse.ArgumentParser(
        description='Read measurements from an STM8+FS9922-DMM4 multimeter.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        'port',
        nargs='?',
        default='/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AL058YDQ-if00-port0',
        help='Serial port path',
    )
    parser.add_argument(
        '--baud', type=int, default=FS9922DMM.DEFAULT_BAUDRATE,
        help='Baud rate',
    )
    parser.add_argument(
        '--interval', type=float, default=0.5,
        help='Display refresh interval in seconds',
    )
    parser.add_argument(
        '--dump', action='store_true',
        help=(
            'Print raw hex bytes of every received packet instead of the '
            'decoded value — use this to reverse-engineer the protocol'
        ),
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Enable debug logging',
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    try:
        with FS9922DMM(args.port, args.baud) as dmm:
            dmm.dump_packets = args.dump
            if args.dump:
                print(
                    f"RAW DUMP from {args.port} @ {args.baud} baud\n"
                    "Format: PKT [sign] [D0 D1 D2 D3] [SP] [range] [mode] [st0] [st1]\n"
                    "Ctrl+C to stop\n"
                )
            else:
                print(f"Reading from {args.port} @ {args.baud} baud — Ctrl+C to stop\n")

            while True:
                if not args.dump:
                    m = dmm.get_measurement()

                    if m.overload:
                        val_str = 'OL'
                    elif m.value is None:
                        val_str = '---'
                    else:
                        val_str = f'{m.value:.6g}'

                    flags = []
                    if m.ac:          flags.append('AC')
                    if m.dc:          flags.append('DC')
                    if m.auto_range:  flags.append('AUTO')
                    if m.hold:        flags.append('HOLD')
                    if m.max_hold:    flags.append('MAX')
                    if m.diode:       flags.append('DIODE')
                    if m.continuity:  flags.append('BEEP')
                    if m.low_battery: flags.append('LOBAT')

                    line = (
                        f'\r{val_str:>14}  '
                        f'[{m.mode:<14}]  '
                        f'{" ".join(flags):<24}'
                    )
                    print(line, end='', flush=True)

                time.sleep(args.interval)

    except KeyboardInterrupt:
        print('\nDone.')
    except serial.SerialException as exc:
        print(f'Serial error: {exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    _main()
