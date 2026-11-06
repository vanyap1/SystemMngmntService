"""Driver for the 2-channel SCPI power supply "SCPI CTRL 2CH PSU" (MultichannelCerPsu, SAMD21 + W5500).

Raw SCPI over TCP port 8080: one connection per command — connect, send "<cmd>\\r\\n", read the answer
until the controller closes the connection. Answers starting with "ERROR" raise PsuError. The controller has
only 8 sockets, so a refused connection is retried a few times. Command reference: http://<ip>/#scpi.

    from instruments.psu import PSU

    psu = PSU("192.168.1.91")
    psu.setVoltage(1, 12.0)
    psu.setCurrent(1, 0.5)
    psu.on(1)
    v, i = psu.getVoltage(1), psu.getCurrent(1)
    psu.off(1)                      # also clears a latched protection (OCP / OVP)

Channels are 1 and 2. Getters return floats in V / A / W (None never — a bad answer raises PsuError).
"""
import re
import socket
import threading
import time
from typing import Dict, List, Optional


class PsuError(Exception):
    """Controller answered "ERROR: ..." or cannot be reached."""


_DATA_FIELDS = ("voltage", "voltage_kelvin", "current", "temperature", "set_voltage", "set_current",
                "power", "cv", "cc", "online")       # online = PSU module connected (output state: isOn())
_OCP_FIELDS = ("soft_ocp", "ocp_tripped", "ocp_limit", "protect_code", "current_source")
PROTECT_NAMES = ("normal", "OVP", "OCP", "OPP", "LVP", "OAH", "OHP", "OTP", "OEP", "OWH", "ICP")
RESET_CAUSES = {1: "power-on", 2: "brown-out 1.2 V", 4: "brown-out 3.3 V", 16: "reset pin", 32: "watchdog",
                64: "system reset"}
LOG_EVENTS = {1: "Boot", 2: "Config defaults", 3: "Config write failed", 4: "PSU init failed", 5: "PSU link lost",
              6: "PSU link restored", 7: "PSU protection", 8: "Overcurrent off", 9: "EXT module error",
              10: "Onboard ADC error", 11: "DMM calibrated", 12: "EXT zero stored", 13: "EXT calibrated",
              14: "Calibration failed", 15: "DMM calibration cleared", 16: "EXT_IO no response",
              17: "Firmware update", 18: "Config erased", 19: "Network reset", 20: "Log cleared"}


class PSU:
    DEFAULT_PORT = 8080

    def __init__(self, host: str = "192.168.1.91", port: int = DEFAULT_PORT, timeout: float = 3.0,
                 retries: int = 5) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()   # one command at a time (also from a TestWatch check)

    # ------------------------------------------------------------------ #
    #  Raw access
    # ------------------------------------------------------------------ #
    def query(self, cmd: str) -> str:
        """Send one command, return the answer text (without the trailing CR LF)."""
        if "\r" in cmd or "\n" in cmd:
            raise ValueError("one command per call")
        last = None
        with self._lock:
            for attempt in range(self.retries):
                try:
                    with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                        s.sendall(cmd.encode("ascii") + b"\r\n")
                        data = b""
                        while True:
                            chunk = s.recv(4096)
                            if not chunk:
                                break
                            data += chunk
                    answer = data.decode("utf-8", errors="replace").rstrip("\r\n")
                    if answer.upper().startswith("ERROR"):
                        raise PsuError(f"{cmd}: {answer}")
                    return answer
                except (ConnectionRefusedError, ConnectionResetError) as e:   # all sockets busy: retry
                    last = e
                    time.sleep(0.05 * (attempt + 1))
                except socket.timeout as e:
                    last = e
                    break
                except OSError as e:
                    last = e
                    break
        raise PsuError(f"{cmd}: no answer from {self.host}:{self.port} ({last})")

    def command(self, cmd: str) -> str:
        """Send a setting command; the answer must not be an error (raises PsuError)."""
        return self.query(cmd)

    def _float(self, cmd: str) -> float:
        answer = self.query(cmd)
        try:
            return float(answer.split(",")[0])
        except ValueError:
            raise PsuError(f"{cmd}: unexpected answer {answer!r}")

    @staticmethod
    def _ch(ch: int) -> int:
        if ch not in (1, 2):
            raise ValueError("channel must be 1 or 2")
        return ch

    # ------------------------------------------------------------------ #
    #  Output
    # ------------------------------------------------------------------ #
    def setVoltage(self, ch: int, volts: float) -> None:
        """Voltage preset, V."""
        self.command(f"VOLT:{self._ch(ch)}:{float(volts):.2f}")

    def setCurrent(self, ch: int, amps: float) -> None:
        """Current limit, A (the controller's overcurrent shutdown is limit + 1 A)."""
        self.command(f"CURR:{self._ch(ch)}:{float(amps):.3f}")

    def on(self, ch: int) -> None:
        self.command(f"OUT:{self._ch(ch)}:1")

    def off(self, ch: int) -> None:
        """Output off; also clears a latched protection (OCP, OVP) so the channel can be switched on again."""
        self.command(f"OUT:{self._ch(ch)}:0")

    def setOutput(self, ch: int, enabled: bool) -> None:
        self.on(ch) if enabled else self.off(ch)

    def allOff(self) -> None:
        """Both outputs off (protections cleared) — use it in finalize()."""
        self.command("RESET")

    def isOn(self, ch: int) -> bool:
        return self.query(f"STATUS:{self._ch(ch)}?").strip() == "1"

    def setup(self, ch: int, volts: float, amps: float, on: bool = True) -> None:
        """Preset voltage and current limit, then switch the output on (or leave it off)."""
        self.setVoltage(ch, volts)
        self.setCurrent(ch, amps)
        self.setOutput(ch, on)

    # ------------------------------------------------------------------ #
    #  Measurements
    # ------------------------------------------------------------------ #
    def getVoltage(self, ch: int) -> float:
        """Measured output voltage, V (INA228 on the EXT module if present, otherwise the PSU)."""
        return self._float(f"VOLT:{self._ch(ch)}?")

    def getCurrent(self, ch: int) -> float:
        """Measured output current, A."""
        return self._float(f"CURR:{self._ch(ch)}?")

    def getPower(self, ch: int) -> float:
        """Output power, W."""
        return self._float(f"POWER:{self._ch(ch)}?")

    def getData(self) -> Dict[int, dict]:
        """Live data of both channels from one request (GET_PSU_DATA):
        {1: {voltage, voltage_kelvin, current, temperature, set_voltage, set_current, power, cv, cc, online,
             input_voltage, soft_ocp, ocp_tripped, ocp_limit, ...}, 2: {...}, 'remote': bool}"""
        raw = self.query("GET_PSU_DATA").split(",")

        def num(i):
            try:
                return float(raw[i])
            except (IndexError, ValueError):
                return None
        out = {}
        for ch, base in ((1, 0), (2, 10)):
            d = {name: num(base + k) for k, name in enumerate(_DATA_FIELDS)}
            for k in ("cv", "cc", "online"):
                d[k] = bool(d[k])
            if d["temperature"] is not None:
                d["temperature"] = int(d["temperature"])
            out[ch] = d
        out["remote"] = bool(num(20))
        if len(raw) >= 27:
            out[1]["input_voltage"], out[2]["input_voltage"] = num(21), num(24)
        if len(raw) >= 37:
            for ch, base in ((1, 27), (2, 32)):
                for k, name in enumerate(_OCP_FIELDS):
                    out[ch][name] = num(base + k)
                for k in ("soft_ocp", "ocp_tripped"):
                    out[ch][k] = bool(out[ch][k])
                for k in ("protect_code", "current_source"):
                    out[ch][k] = int(out[ch][k] or 0)
        return out

    def waitVoltage(self, ch: int, target: float, tolerance: float = 0.1, timeout: float = 5.0) -> Optional[float]:
        """Wait until the measured voltage is within target ± tolerance; returns the last reading
        (check it with ts.numericLimitTest) — also when the timeout expires."""
        end = time.time() + timeout
        v = self.getVoltage(ch)
        while abs(v - target) > tolerance and time.time() < end:
            time.sleep(0.1)
            v = self.getVoltage(ch)
        return v

    # ------------------------------------------------------------------ #
    #  Protection and front panel
    # ------------------------------------------------------------------ #
    def setOcp(self, ch: int, amps: float) -> None:
        self.command(f"OCP:{self._ch(ch)}:{float(amps):.2f}")

    def getOcp(self, ch: int) -> float:
        return self._float(f"OCP:{self._ch(ch)}?")

    def setSoftOcp(self, ch: int, enabled: bool) -> None:
        """Software OCP (saved in the controller's flash)."""
        self.command(f"SWOCP:{self._ch(ch)}:{1 if enabled else 0}")

    def getSoftOcp(self, ch: int) -> bool:
        return self.query(f"SWOCP:{self._ch(ch)}?").strip() == "1"

    def setOvp(self, ch: int, volts: float) -> None:
        """Over-voltage protection, V — set it before raising the voltage."""
        self.command(f"OVP:{self._ch(ch)}:{float(volts):.2f}")

    def isTripped(self, ch: int) -> bool:
        """Software OCP has switched the output off."""
        return bool(self.getData()[ch].get("ocp_tripped"))

    def setRemoteLock(self, ch: int, locked: bool) -> None:
        """Lock / unlock the PSU front panel (switches the output off)."""
        self.command(f"REM:{self._ch(ch)}:{1 if locked else 0}")

    def getRemoteLock(self, ch: int) -> bool:
        return self.query(f"REM:{self._ch(ch)}?").strip() == "1"

    def protection(self, ch: int) -> str:
        """Protection state of the PSU module: 'normal', 'OVP', 'OCP', 'OPP', 'OTP', ..."""
        code = self.getData()[ch].get("protect_code", 0) or 0
        return PROTECT_NAMES[code] if 0 <= code < len(PROTECT_NAMES) else f"code {code}"

    def setBacklight(self, ch: int, level: int) -> None:
        """PSU display backlight 0..5."""
        if not 0 <= int(level) <= 5:
            raise ValueError("backlight 0..5")
        self.command(f"BLK:{self._ch(ch)}:{int(level)}")

    def getBacklight(self, ch: int) -> int:
        return int(self._float(f"BLK:{self._ch(ch)}?"))

    def setKelvin(self, ch: int, enabled: bool) -> None:
        """Virtual Kelvin correction: the PSU preset follows the INA228 (load-side) voltage."""
        self.command(f"VCORR:{self._ch(ch)}:{1 if enabled else 0}")

    @staticmethod
    def _bus(slave, baud):
        if slave is None and baud is None:
            return ""
        return f":{int(slave if slave is not None else 1)}" + (f":{int(baud)}" if baud is not None else "")

    def regRead(self, ch: int, addr: int, count: int = 1, slave: int = None, baud: int = None) -> List[int]:
        """Raw Modbus registers of the PSU module (decimal address, count 1..64) -> [values]."""
        answer = self.query(f"REG?:{self._ch(ch)}:{int(addr)}:{int(count)}{self._bus(slave, baud)}")
        # "Reg 0x0(0): 0x4b0(1200)" -> 1200
        return [int(x) for x in re.findall(r":\s*0x[0-9a-fA-F]+\((\d+)\)", answer)]

    def regWrite(self, ch: int, addr: int, value: int, slave: int = None, baud: int = None) -> None:
        """Write a raw Modbus register of the PSU module (see SYS Tools of the web page for the map)."""
        self.command(f"REG:{self._ch(ch)}:{int(addr)}:{int(value)}{self._bus(slave, baud)}")

    # ------------------------------------------------------------------ #
    #  EXT modules: INA228 / ADS1115 measurements, TCA9535 I/O
    # ------------------------------------------------------------------ #
    def extMeasure(self, ext: int = 1, rng: int = 1) -> dict:
        """EXT1 / EXT2 module: {'type': 'INA228', 'voltage', 'current', 'power'} or
        {'type': 'ADS1115', 'voltage', 'raw'} (rng 0 = 0-5 V, 1 = 0-100 V) or {'type': 'NONE'}."""
        if ext not in (1, 2):
            raise ValueError("ext must be 1 or 2")
        v = self.query(f"ADC:MEAS:EXT{ext}:ALL?{int(rng)}").split(",")
        if v[0] == "INA228":
            return {"type": "INA228", "voltage": float(v[1]), "current": float(v[2]), "power": float(v[3])}
        if v[0] == "ADS1115":
            return {"type": "ADS1115", "voltage": float(v[1]), "raw": int(float(v[2]))}
        return {"type": v[0] or "NONE"}

    @staticmethod
    def _ext(ext: int) -> int:
        if ext not in (1, 2):
            raise ValueError("ext must be 1 or 2")
        return ext

    def extType(self, ext: int = 1) -> str:
        """Module plugged into EXT1 / EXT2: 'INA228', 'ADS1115' or 'NONE'."""
        return self.extMeasure(ext)["type"]

    def extVoltage(self, ext: int = 1, rng: int = 1) -> float:
        """EXT voltage, V (ADS1115: range 0 = 0-5 V, 1 = 0-100 V; ignored for INA228)."""
        return self._float(f"ADC:MEAS:EXT{self._ext(ext)}:VOLT?{int(rng)}")

    def extCurrent(self, ext: int = 1) -> float:
        """EXT current, A (INA228 only, 10 mΩ shunt)."""
        return self._float(f"ADC:MEAS:EXT{self._ext(ext)}:AMP?")

    def extPower(self, ext: int = 1) -> float:
        """EXT power V × I, W (INA228 only)."""
        return self._float(f"ADC:MEAS:EXT{self._ext(ext)}:POW?")

    def extVI(self, ext: int = 1) -> tuple:
        """(voltage, current) of the INA228 from one read."""
        v, i = self.query(f"ADC:MEAS:EXT{self._ext(ext)}:VI?").split(",")[:2]
        return float(v), float(i)

    # ------------------------------------------------------------------ #
    #  Onboard DMM: 4 channels (AIN0..AIN3), range 0 = 0-5 V, 1 = 0-100 V
    # ------------------------------------------------------------------ #
    def onboardVoltage(self, ch: int, rng: int = 1) -> float:
        """Onboard DMM channel 0-3, range 0 (0-5 V) or 1 (0-100 V), V."""
        return self.onboardRaw(ch, rng)[0]

    def onboardRaw(self, ch: int, rng: int = 1) -> tuple:
        """(voltage, raw ADC counts) of an onboard DMM channel."""
        if ch not in (0, 1, 2, 3) or rng not in (0, 1):
            raise ValueError("onboard channel 0..3, range 0/1")
        v, raw = self.query(f"ADC:MEAS:ONBOARD?{ch},{rng}").split(",")[:2]
        return float(v), int(float(raw))

    def adcInfo(self) -> str:
        """ADC hardware summary."""
        return self.query("ADC:INFO?")

    def adcReinit(self) -> str:
        """Re-initialise the ADCs and detect the EXT module types again (after plugging a module)."""
        return self.command("ADC:REINIT")

    # ------------------------------------------------------------------ #
    #  Calibration (service): onboard DMM and EXT ADS1115
    # ------------------------------------------------------------------ #
    def onboardCalData(self) -> List[dict]:
        """[{'ch', 'range', 'factor', 'zero'}] for every onboard channel and range."""
        out = []
        for line in self.query("ADC:CALL:ONBOARD:DATA?").splitlines():
            p = line.split(",")
            if len(p) >= 4:
                out.append({"ch": int(p[0]), "range": int(p[1]), "factor": float(p[2]), "zero": int(float(p[3]))})
        return out

    def onboardCalibrate(self, ch: int, rng: int) -> str:
        """Calibrate an onboard channel against the internal reference (inputs disconnected!), saved to flash."""
        return self.command(f"ADC:CALL:ONBOARD?{int(ch)},{int(rng)}")

    def setOnboardFactor(self, ch: int, rng: int, factor: float) -> str:
        """Set an onboard coefficient by hand (zero reset to 0), saved to flash."""
        return self.command(f"ADC:CALLSET: {int(ch)} {int(rng)} {float(factor):.10f}")

    def clearOnboardCal(self) -> str:
        """Reset all onboard constants (coefficient 1.0, zero 0), saved to flash."""
        return self.command("CLEAR_CALLIBRATION")

    def setCalSource(self, enabled: bool) -> str:
        """Internal calibration reference of the onboard DMM on / off."""
        return self.command(f"ADC:CALLSRC: {1 if enabled else 0}")

    def getRefVoltage(self) -> float:
        """Reference voltage used for the onboard calibration, V."""
        return self._float("GET_REF_VOLTAGE")

    def setRefVoltage(self, volts: float) -> str:
        """Reference voltage 2.0-5.999 V (RAM; saved with the next calibration)."""
        return self.command(f"SET_REF_VOLTAGE {float(volts):.3f}")

    def extCalData(self, ext: int = 1) -> dict:
        """EXT ADS1115 constants: {'gain0', 'zero0', 'gain1', 'zero1'} (range 0 = 0-5 V, 1 = 0-100 V)."""
        g0, z0, g1, z1 = self.query(f"ADC:CALL:EXT{self._ext(ext)}:DATA?").split(",")[:4]
        return {"gain0": float(g0), "zero0": int(float(z0)), "gain1": float(g1), "zero1": int(float(z1))}

    def extCalZero(self, ext: int, rng: int) -> str:
        """EXT ADS1115 step 1: input shorted (0 V) — store the zero of a range."""
        return self.command(f"ADC:CALL:EXT{self._ext(ext)}:ZERO?{int(rng)}")

    def extCalibrate(self, ext: int, rng: int, ref_volts: float) -> str:
        """EXT ADS1115 step 2: a known voltage applied, ref_volts = reading of the reference meter."""
        return self.command(f"ADC:CALL:EXT{self._ext(ext)}?{int(rng)},{float(ref_volts):.4f}")

    def extCalibrateWithPsu(self, ch: int, rng: int) -> str:
        """EXT ADS1115 of a channel calibrated with its own PSU as the source (load disconnected, takes seconds)."""
        return self.command(f"CALL:{self._ch(ch)}:{int(rng)}")

    def ioList(self) -> List[dict]:
        """Configured EXT_IO modules: [{'n', 'type', 'addr', 'name', 'labels'}]."""
        answer = self.query("EXTIO:LIST?")
        if answer.strip() == "NONE":
            return []
        out = []
        for line in answer.splitlines():
            p = line.split("|")
            if len(p) >= 4:
                out.append({"n": int(p[0]), "type": p[1], "addr": p[2], "name": p[3],
                            "labels": [x for x in p[4:]]})
        return out

    def ioIn(self, module: int, ch: int) -> int:
        """Input channel level (0 / 1)."""
        return int(self.query(f"EXTIO:IN? {int(module)},{int(ch)}").strip())

    def ioOut(self, module: int, ch: int, value: int) -> int:
        """Set an output channel; returns the actual level read back."""
        return int(self.query(f"EXTIO:OUT {int(module)},{int(ch)},{1 if value else 0}").strip())

    def ioOutAll(self, module: int, mask: int) -> int:
        """Set all outputs of a module at once (bit = channel); returns the actual levels."""
        return int(self.query(f"EXTIO:OUT:ALL {int(module)},{int(mask) & 0xFFFF:04X}").strip(), 16)

    def ioStates(self) -> List[dict]:
        """State of every module (see ioState)."""
        out = []
        for line in self.query("EXTIO:STATE?").splitlines():
            p = line.strip().split("|")
            if len(p) >= 6:
                out.append({"n": int(p[0]), "type": p[1], "addr": p[2], "online": p[3] == "1",
                            "pins": int(p[4], 16), "setpoint": int(p[5], 16)})
        return out

    def ioOutRead(self, module: int, ch: int) -> int:
        """Actual level (feedback) of an output channel."""
        return int(self.query(f"EXTIO:OUT? {int(module)},{int(ch)}").strip())

    def ioPin(self, module: int, ch: int) -> int:
        """Level of any pin (input or output feedback) from the module state."""
        return (self.ioState(module)["pins"] >> int(ch)) & 1

    @staticmethod
    def _io_desc(kind, addr, name, labels):
        kind = str(kind).upper()
        if kind not in ("IN", "OUT", "MIX"):
            raise ValueError("type IN, OUT or MIX")
        addr = f"{int(addr, 16) if isinstance(addr, str) else int(addr):02X}"
        parts = [kind, addr, name] + list(labels or [])
        if any(("|" in str(x) or ";" in str(x)) for x in parts):
            raise ValueError("'|' and ';' are not allowed")
        return "|".join(str(x) for x in parts)

    def ioAdd(self, kind: str, addr, name: str, labels=()) -> int:
        """Add a TCA9535 module (max 8): kind IN / OUT / MIX (MIX = inputs 0..7, outputs 8..15),
        addr 0x20..0x27 (int or hex string '21'), name and up to 16 channel labels. Returns its number."""
        answer = self.command("EXTIO:ADD " + self._io_desc(kind, addr, name, labels))
        return int(answer.split(":")[-1])

    def ioEdit(self, module: int, kind: str, addr, name: str, labels=()) -> None:
        """Replace module n description (changing type / address resets its outputs)."""
        self.command(f"EXTIO:EDIT {int(module)}|" + self._io_desc(kind, addr, name, labels))

    def ioDelete(self, module: int) -> None:
        """Delete module n (outputs off, following modules are renumbered)."""
        self.command(f"EXTIO:DEL {int(module)}")

    def ioClear(self) -> None:
        """Delete all modules (outputs off)."""
        self.command("EXTIO:CLEAR")

    def ioState(self, module: int) -> dict:
        """{'n', 'type', 'addr', 'online', 'pins', 'setpoint'} (pins / setpoint as int bit masks)."""
        p = self.query(f"EXTIO:STATE? {int(module)}").strip().split("|")
        return {"n": int(p[0]), "type": p[1], "addr": p[2], "online": p[3] == "1",
                "pins": int(p[4], 16), "setpoint": int(p[5], 16)}

    # ------------------------------------------------------------------ #
    #  Device
    # ------------------------------------------------------------------ #
    def identify(self) -> str:
        """*IDN? — model, firmware, build date, serial (several lines)."""
        return self.query("*IDN?")

    def deviceId(self) -> tuple:
        """(model, serial)."""
        model, _, serial = self.query("GET_DEVICE_ID").partition("|")
        return model, serial

    def isReady(self) -> bool:
        """Controller status READY (not FAULT)."""
        return self.query("GET_DEVICE_INFO").rstrip().endswith("READY")

    def firmwareVersion(self) -> str:
        """Controller software version, e.g. '2.90'."""
        for line in self.identify().splitlines():
            if line.lower().startswith("version:"):
                return line.split(":", 1)[1].strip()
        return self.deviceInfo()["firmware"]

    def hwVersion(self) -> str:
        return self.query("HW:VER?").strip()

    def deviceInfo(self) -> dict:
        """{'ip', 'mac', 'ports', 'firmware', 'uptime_s', 'status'}."""
        head, *rest = self.query("GET_DEVICE_INFO").split(",")
        ip, _, mac = head.partition(" ")
        d, h, m, sec = (int(float(x)) for x in rest[3:7])
        return {"ip": ip, "mac": mac, "ports": (int(rest[0]), int(rest[1])), "firmware": rest[2],
                "uptime_s": ((d * 24 + h) * 60 + m) * 60 + sec, "status": rest[7].strip()}

    def ping(self) -> bool:
        """The controller answers."""
        try:
            return self.query("STATUS").startswith("OK")
        except PsuError:
            return False

    def resetCause(self) -> str:
        """Why the controller started last time: 'power-on', 'watchdog', ..."""
        bits = int(self._float("SYST:RESET?"))
        return ", ".join(t for b, t in RESET_CAUSES.items() if bits & b) or f"cause {bits}"

    def logInfo(self) -> dict:
        """Event log: {'entries', 'lost', 'capacity'}."""
        e, lost, cap = self.query("SYST:LOG:INFO?").split(",")[:3]
        return {"entries": int(e), "lost": int(lost), "capacity": int(cap)}

    def log(self, count: int = 32, start: int = 0) -> List[dict]:
        """Event log entries, newest first (max 32 per call): [{'seq', 'boot', 'uptime_s', 'code', 'event', 'src', 'value'}]."""
        answer = self.query(f"SYST:LOG? {int(start)},{min(int(count), 32)}")
        out = []
        if answer.strip() == "NONE":
            return out
        for line in answer.splitlines():
            p = line.split(",")
            if len(p) >= 6:
                seq, boot, up, code, src, value = (int(float(x)) for x in p[:6])
                out.append({"seq": seq, "boot": boot, "uptime_s": up, "code": code,
                            "event": LOG_EVENTS.get(code, f"Event {code}"), "src": src, "value": value})
        return out

    def clearLog(self) -> None:
        self.command("SYST:LOG:CLEAR")

    def inventory(self) -> str:
        """Model, serial, network, calibration constants, modules and event log as text."""
        return self.query("INVENTORY?")

    # ------------------------------------------------------------------ #
    #  External I2C bus of the controller
    # ------------------------------------------------------------------ #
    def i2cScan(self) -> List[int]:
        """Addresses answering on the external I2C bus (0x08..0x77)."""
        answer = self.query("SOUR:I2C:SCAN?").strip()
        return [] if answer == "NONE" else [int(x, 16) for x in answer.split(",") if x.strip()]

    def i2cRead(self, addr: int, reg: int, length: int = 1) -> List[int]:
        """Read 1..32 bytes from device `addr` at register `reg`."""
        if not 1 <= int(length) <= 32:
            raise ValueError("length 1..32")
        answer = self.query(f"SOUR:I2C:READ? {int(addr):02X},{int(reg):02X},{int(length):02X}")
        return [int(x, 16) for x in answer.strip().split(",")]

    def i2cWrite(self, addr: int, reg: int, data) -> None:
        """Write bytes (list of ints, max 32) to device `addr` at register `reg`."""
        data = list(data)
        if not 1 <= len(data) <= 32:
            raise ValueError("1..32 data bytes")
        self.command(f"SOUR:I2C:WRITE {int(addr):02X},{int(reg):02X}," + ",".join(f"{int(b) & 0xFF:02X}" for b in data))

    def close(self) -> None:
        """Nothing to close (one connection per command); kept for symmetry with the DMM drivers."""


if __name__ == "__main__":
    # Read-only check: nothing is switched or changed.  python3 instruments/psu.py [host]
    import sys
    psu = PSU(sys.argv[1] if len(sys.argv) > 1 else "192.168.1.91")
    print(psu.identify())
    print("ready:", psu.isReady(), " id:", psu.deviceId())
    for ch in (1, 2):
        print(f"CH{ch}: on={psu.isOn(ch)}  {psu.getVoltage(ch):.3f} V  {psu.getCurrent(ch):.3f} A  {psu.getPower(ch):.2f} W")
    d = psu.getData()
    print("data:", {k: d[1][k] for k in ("set_voltage", "set_current", "cv", "cc", "input_voltage", "ocp_limit")})
    print("EXT1:", psu.extMeasure(1))
    print("IO modules:", [(m["n"], m["type"], m["name"]) for m in psu.ioList()])
