"""testPlatform/instruments: scpi base, Rigol scope, OWON multimeter / load, SerialTerm, SshTerm, ParamFile.

Instruments are simulated: a SCPI server on localhost, a pseudo terminal, a fake ``ssh`` program, temp folders —
no real instrument, port or host is contacted.
"""
import json
import os
import socket
import stat
import struct
import sys
import tempfile
import threading
import time
import unittest

from tests.support import ROOT

sys.path.insert(0, os.path.join(ROOT, 'testPlatform'))
from instruments.owon_xdm import OWON_XDM  # noqa: E402
from instruments.owon_oel import OWON_OEL  # noqa: E402
from instruments.param_file import ParamFile, format_value, parse_value  # noqa: E402
from instruments.rigol_dho import RigolScope  # noqa: E402
from instruments.rigol_dho804 import RIGOL_DHO804  # noqa: E402
from instruments.rigol_dho924 import RIGOL_DHO924  # noqa: E402
from instruments.scpi import InstrumentError, ScpiInstrument  # noqa: E402
from instruments.serial_term import SerialTerm, TermError  # noqa: E402
from instruments.siglent_sdg import parse_params  # noqa: E402
from instruments.siglent_sdg1032x import SIGLENT_SDG1032X  # noqa: E402
from instruments.siglent_sdl1020x import SIGLENT_SDL1020X  # noqa: E402
from instruments.siglent_sds802xhd import SIGLENT_SDS802XHD  # noqa: E402
from instruments.siglent_spd1305x import SIGLENT_SPD1305X  # noqa: E402
from instruments.ssh_term import SshError, SshTerm  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 50


class FakeScpi:
    """Line based SCPI server: answers queries from ``answer(cmd)``, records every line; one connection at a time."""

    def __init__(self, answer):
        self.answer, self.lines = answer, []
        self.drop_next = False
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            buf = b''
            with conn:
                while True:
                    try:
                        data = conn.recv(4096)
                    except OSError:
                        break
                    if not data:
                        break
                    buf += data
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        cmd = line.decode().strip()
                        self.lines.append(cmd)
                        if self.drop_next:
                            self.drop_next = False
                            conn.close()
                            break
                        ans = self.answer(cmd)
                        if ans is not None:
                            conn.sendall(ans if isinstance(ans, bytes) else ans.encode() + b'\n')
                    else:
                        continue
                    break

    def close(self):
        self.sock.close()


def block(data):
    n = str(len(data)).encode()
    return b'#' + str(len(n)).encode() + n + data + b'\n'


class Scope(unittest.TestCase):
    def setUp(self):
        self.fmt = 'WORD'

        def answer(cmd):
            if cmd == '*IDN?':
                return 'RIGOL TECHNOLOGIES,DHO924,DHO9A0000,00.01.05'
            if cmd == ':MEASure:ITEM? VPP,CHANnel1':
                return '3.0345E+00'
            if cmd == ':MEASure:ITEM? VPP,CHANnel2':
                return '9.9E37'
            if cmd == ':MEASure:ITEM? PDUTy,CHANnel1':
                return '5.0001E-01'
            if cmd == ':WAVeform:FORMat?':
                return self.fmt
            if cmd.startswith(':WAVeform:FORMat '):
                self.fmt = cmd.split()[1]
                return None
            if cmd == ':WAVeform:PREamble?':
                return '0,0,4,1,2.0E-6,-1.0E-3,0,0.5,-28,128'
            if cmd == ':WAVeform:DATA?':
                return block(bytes([100, 128, 156, 200]))
            if cmd == ':DISPlay:DATA? PNG':
                return block(PNG)
            if cmd == ':TRIGger:STATus?':
                return 'STOP'
            if cmd == ':SYSTem:ERRor?':
                return '0,"No error"'
            if cmd.endswith('?'):
                return '1'
            return None
        self.srv = FakeScpi(answer)
        self.s = RigolScope('127.0.0.1', self.srv.port, timeout=2)

    def tearDown(self):
        self.s.close()
        self.srv.close()

    def test_model_classes_check_the_identity(self):
        for cls, ok in ((RIGOL_DHO924, True), (RIGOL_DHO804, False)):
            s = cls('127.0.0.1', self.srv.port, timeout=2)
            try:
                if ok:
                    self.assertEqual(s.checkModel(), 'DHO924')
                else:
                    with self.assertRaisesRegex(InstrumentError, 'DHO924 answers, DHO804 expected'):
                        s.checkModel()
            finally:
                s.close()                                 # the fake serves one connection at a time
        self.assertEqual(self.s.checkModel(), 'DHO924')            # generic class accepts any model

    def test_measurements(self):
        self.assertIn('DHO924', self.s.idn())
        self.assertAlmostEqual(self.s.getVoltPkPk(1), 3.0345)
        self.assertIsNone(self.s.getVoltPkPk(2))                       # 9.9E37 = cannot measure
        self.assertAlmostEqual(self.s.getDutyCycle(1), 50.001)         # ratio → %
        self.assertEqual(self.s.errors(), [])
        with self.assertRaises(ValueError):
            self.s.getVoltPkPk(5)

    def sync(self):
        self.s.query('*OPC?')                                          # commands without an answer are processed

    def test_waveform_scaling_and_format_restored(self):
        t, v = self.s.getWaveform(1)
        self.sync()
        self.assertEqual(len(v), 4)
        self.assertAlmostEqual(v[0], (100 + 28 - 128) * 0.5)
        self.assertAlmostEqual(v[3], (200 + 28 - 128) * 0.5)
        self.assertAlmostEqual(t[1] - t[0], 2.0e-6)
        self.assertEqual(self.fmt, 'WORD')                             # the scope's setting is put back
        self.assertIn(':WAVeform:SOURce CHANnel1', self.srv.lines)

    def test_screenshot_and_settings(self):
        path = os.path.join(tempfile.mkdtemp(), 's.png')
        self.s.screenshot(path)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), PNG)
        self.s.setTrigger(2, 1.5, 'neg', 'single'[:4])
        self.sync()
        self.assertEqual(self.srv.lines[-5:-1], [':TRIGger:EDGE:SOURce CHANnel2', ':TRIGger:EDGE:SLOPe NEG',
                                               ':TRIGger:EDGE:LEVel 1.5', ':TRIGger:SWEep SING'])
        self.s.single()
        self.assertTrue(self.s.waitTriggered(1))
        with self.assertRaises(ValueError):
            self.s.setCoupling(1, 'XX')

    def test_reconnect_once_after_a_dropped_connection(self):
        self.s.idn()
        self.srv.drop_next = True                                     # the server closes on the next line
        self.assertIn('DHO924', self.s.idn())                         # re-opened and repeated


class Scpi(unittest.TestCase):
    def test_timeout_and_unreachable(self):
        srv = FakeScpi(lambda cmd: None)                              # never answers
        inst = ScpiInstrument(host='127.0.0.1', port=srv.port, timeout=0.3)
        t0 = time.time()
        with self.assertRaises(InstrumentError) as cm:
            inst.query('*IDN?')
        self.assertIn('no answer', str(cm.exception))
        self.assertLess(time.time() - t0, 2)
        inst.close()
        srv.close()
        with self.assertRaises(InstrumentError):
            ScpiInstrument(host='127.0.0.1', port=1, timeout=0.5).query('*IDN?')
        with self.assertRaises(ValueError):
            ScpiInstrument(host='x', serial='/dev/ttyUSB0')

    def test_serial_transport_on_a_pty(self):
        master, slave = os.openpty()

        def device():
            buf = b''
            while True:
                try:
                    buf += os.read(master, 100)
                except OSError:
                    return
                if b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    if line == b'*IDN?':
                        os.write(master, b'OWON,XDM1041,123,V1\n')
        threading.Thread(target=device, daemon=True).start()
        try:
            inst = ScpiInstrument(serial=os.ttyname(slave), timeout=1)
            self.assertEqual(inst.idn(), 'OWON,XDM1041,123,V1')
            inst.close()
        finally:
            os.close(slave)
            os.close(master)


class Owon(unittest.TestCase):
    def setUp(self):
        self.reads = []

        def answer(cmd):
            if cmd == 'MEAS1?':
                return self.reads.pop(0) if self.reads else '1.2345E+00'
            if cmd == 'INP?':
                return 'ON'
            if cmd == 'FUNC?':
                return 'CURR'
            if cmd.startswith('MEAS:'):
                return {'MEAS:VOLT?': '12.01', 'MEAS:CURR?': '1.499', 'MEAS:POW?': '18.0'}[cmd]
            return None
        self.srv = FakeScpi(answer)

    def tearDown(self):
        self.srv.close()

    def test_dmm_switches_function_once(self):
        d = OWON_XDM(host='127.0.0.1', port=self.srv.port, timeout=2)
        d.SETTLE = {k: 0 for k in ('vdc', 'res', 'cap', 'temp')}
        OWON_XDM.SETTLE.setdefault('vdc', 0)
        self.assertAlmostEqual(d.getVoltDC(), 1.2345)
        self.assertAlmostEqual(d.getVoltDC(), 1.2345)
        self.assertEqual(self.srv.lines.count('CONF:VOLT:DC'), 1)      # no second switch
        self.reads = ['ignored', 'OVLD']
        self.assertIsNone(d.getResistance())                          # first reading after the switch dropped
        self.assertEqual(self.srv.lines.count('CONF:RES'), 1)
        self.assertIn('AUTO', self.srv.lines)
        d.COMMANDS['read'] = 'MEAS?'                                  # per instance, not for the class
        self.assertEqual(OWON_XDM.COMMANDS['read'], 'MEAS1?')
        with self.assertRaises(ValueError):
            d.configure('read')
        d.close()

    def test_load(self):
        ld = OWON_OEL(host='127.0.0.1', port=self.srv.port, timeout=2)
        ld.setup('cc', 1.5)
        self.assertTrue(ld.isOn())                                     # (a query: the writes are processed)
        self.assertEqual(self.srv.lines[-4:-1], ['FUNC CURR', 'CURR 1.5', 'INP ON'])
        self.assertTrue(ld.isOn())
        self.assertEqual(ld.getMode(), 'CC')
        self.assertEqual((ld.getVoltage(), ld.getCurrent(), ld.getPower()), (12.01, 1.499, 18.0))
        self.assertAlmostEqual(ld.waitCurrent(1.5, 0.01, 1), 1.499)
        ld.off()
        ld.isOn()
        self.assertEqual(self.srv.lines[-2], 'INP OFF')
        for bad in (lambda: ld.setCC(-1), lambda: ld.setup('XX', 1)):
            with self.assertRaises(ValueError):
                bad()
        ld.close()


class SiglentLoad(unittest.TestCase):
    """SDL1020X: modes with read-back levels, input state, measurements, protections, empty line after errors."""

    def setUp(self):
        self.st = {'func': 'CURRENT', 'inp': 0, 'lev': {'CUR': 1.0, 'VOL': 1.0, 'RES': 1.0, 'POW': 1.0},
                   'prot': {'CUR': 0, 'POW': 0}, 'errors': ['-113,Undefined header,FOO?'], 'lose': 0, 'misc': {}}
        names = {'CURRent': 'CURRENT', 'VOLTage': 'VOLTAGE', 'RESistance': 'RESISTANCE', 'POWer': 'POWER'}

        def answer(cmd):
            st = self.st
            if cmd == '*IDN?':
                return 'Siglent Technologies,SDL1020X,SDL13GCXA00546,1.1.1.23R4'
            if cmd in ('SYST:ERR?', ':SYSTem:ERRor?'):
                return (st['errors'].pop(0) + '\n') if st['errors'] else '+0, No error'
            if cmd == ':SOUR:FUNC?':
                return st['func']
            if cmd == ':SOUR:INP:STAT?':
                return str(st['inp'])
            on = st['inp']
            meas = {':MEAS:VOLT?': 12.0, ':MEAS:CURR?': st['lev']['CUR'] * on, ':MEAS:POW?': 12 * st['lev']['CUR'] * on,
                    ':MEAS:RES?': 24.0}
            if cmd in meas:
                return f'{meas[cmd]:.6f}'
            parts = cmd.split()
            key = parts[0]
            if key.endswith(':LEV:IMM?'):
                return f"{st['lev'][key.split(':')[2][:3].upper()]:.6f}"
            if key.endswith('?') and key[:-1] in st['misc']:
                return f"{st['misc'][key[:-1]]:.6f}"
            if key.endswith('PROT:STAT?'):
                return str(st['prot'][key.split(':')[2][:3].upper()])
            if len(parts) < 2:
                return None
            if st['lose']:
                st['lose'] -= 1
                return None
            if key == ':SOUR:FUNC':
                st['func'] = names[parts[1]]
            elif key == ':SOUR:INP:STAT':
                st['inp'] = 1 if parts[1] == 'ON' else 0
            elif key.endswith(':LEV:IMM'):
                st['lev'][key.split(':')[2][:3].upper()] = float(parts[1])
            elif key.endswith('PROT:STAT'):
                st['prot'][key.split(':')[2][:3].upper()] = 1 if parts[1] == 'ON' else 0
            else:
                st['misc'][key] = float(parts[1])
            return None
        self.srv = FakeScpi(answer)
        self.ld = SIGLENT_SDL1020X('127.0.0.1', self.srv.port, timeout=1)
        self.ld.WRITE_DELAY = 0

    def tearDown(self):
        self.ld.close()
        self.srv.close()

    def test_modes_input_and_measure(self):
        self.assertEqual(self.ld.checkModel(), 'SDL1020X')
        self.ld.setup('CC', 0.5)
        self.assertTrue(self.ld.isOn())
        self.assertEqual((self.ld.getMode(), self.ld.getLevel()), ('CC', 0.5))
        self.assertEqual(self.ld.measureAll(), (12.0, 0.5, 6.0))
        self.assertEqual(self.ld.waitCurrent(0.5, timeout=0.5), 0.5)
        self.ld.setCR(24)
        self.assertEqual((self.ld.getMode(), self.ld.getLevel()), ('CR', 24.0))
        self.ld.setCP(6)
        self.ld.setCV(10)
        self.assertEqual(self.ld.getLevel('CP'), 6.0)
        self.ld.off()
        self.assertFalse(self.ld.isOn())
        with self.assertRaises(ValueError):
            self.ld.setCC(31)                                # above the SDL1020X 30 A
        with self.assertRaises(ValueError):
            self.ld.setup('XX', 1)

    def test_lost_command_retried_and_protections(self):
        self.st['lose'] = 1
        self.ld.setCC(0.25)                                  # first level write lost, sent again
        self.assertEqual(self.st['lev']['CUR'], 0.25)
        self.ld.setCurrentProtection(1.0)
        self.ld.setPowerProtection(1.0)
        self.assertEqual(self.ld.protection(), {'current': True, 'power': True})
        self.ld.setCurrentProtection(None)
        self.assertFalse(self.ld.protection()['current'])
        self.assertEqual(self.ld.errors(), ['-113,Undefined header,FOO?'])
        self.assertEqual(self.ld.getMode(), 'CC')            # the empty line did not shift the answers


class SiglentGenerator(unittest.TestCase):
    """SDG1032X: BSWV parameters read back, values the generator limits are reported, output / load / burst."""

    def setUp(self):
        def ch():
            return {'BSWV': {'WVTP': 'SINE', 'FRQ': '1000HZ', 'AMP': '4V', 'OFST': '0V', 'PHSE': '0'},
                    'OUTP': 'OFF', 'LOAD': 'HZ', 'BTWV': 'OFF', 'ARB': 'StairUp'}
        self.chs = {'C1': ch(), 'C2': ch()}
        units = {'FRQ': 'HZ', 'AMP': 'V', 'OFST': 'V', 'WIDTH': 'S', 'HLEV': 'V', 'LLEV': 'V'}

        def answer(cmd):
            if cmd == '*IDN?':
                return 'Siglent Technologies,SDG1032X,SDG1XDDXA01104,1.01.01.33R8'
            if cmd == 'STL?':
                return 'STL M10, ExpFal, M2, StairUp'
            head, _, args = cmd.partition(' ')
            c, _, what = head.partition(':')
            st = self.chs.get(c)
            if st is None:
                return None
            if what == 'BSWV?':
                return f"{c}:BSWV " + ','.join(f'{k},{v}' for k, v in st['BSWV'].items())
            if what == 'OUTP?':
                return f"{c}:OUTP {st['OUTP']},LOAD,{st['LOAD']},PLRT,NOR"
            if what in ('BTWV?', 'SWWV?', 'MDWV?'):
                return f"{c}:{what[:-1]} STATE,{st['BTWV'] if what == 'BTWV?' else 'OFF'}"
            if what == 'ARWV?':
                return f"{c}:ARWV INDEX,2,NAME,{st['ARB']}"
            a = args.split(',')
            if what == 'BSWV':
                k, v = a[0], a[1]
                if k == 'AMP' and float(v) > (10 if st['LOAD'] == '50' else 20):
                    v = '10' if st['LOAD'] == '50' else '20'           # the generator limits silently
                st['BSWV'][k] = v + units.get(k, '') if k != 'WVTP' else v
            elif what == 'OUTP':
                if a[0] in ('ON', 'OFF'):
                    st['OUTP'] = a[0]
                elif a[0] == 'LOAD':
                    st['LOAD'] = a[1]
            elif what == 'BTWV' and a[0] == 'STATE':
                st['BTWV'] = a[1]
            elif what == 'ARWV' and a[1] in ('StairUp', 'ExpFal'):
                st['ARB'] = a[1]
            return None
        self.srv = FakeScpi(answer)
        self.g = SIGLENT_SDG1032X('127.0.0.1', self.srv.port, timeout=1)
        self.g.WRITE_DELAY = 0

    def tearDown(self):
        self.g.close()
        self.srv.close()

    def test_parse_params(self):
        self.assertEqual(parse_params('C1:BSWV WVTP,SINE,FRQ,1000HZ,AMP,4V,AMPVRMS,1.414Vrms,PHSE,0'),
                         {'WVTP': 'SINE', 'FRQ': 1000.0, 'AMP': 4.0, 'AMPVRMS': 1.414, 'PHSE': 0.0})

    def test_square_on_off_and_readback(self):
        self.assertEqual(self.g.checkModel(), 'SDG1032X')
        self.g.square(2, 10e3, 3.3, offset=1.65, duty=25)
        b = self.g.getBasic(2)
        self.assertEqual((b['WVTP'], b['FRQ'], b['AMP'], b['OFST'], b['DUTY']), ('SQUARE', 10000.0, 3.3, 1.65, 25.0))
        self.assertTrue(self.g.isOn(2))
        self.assertFalse(self.g.isOn(1))
        self.g.dc(1, 2.5, on=False)
        self.assertEqual((self.g.getWaveform(1), self.g.getOffset(1)), ('DC', 2.5))
        self.g.allOff()
        self.assertFalse(self.g.isOn(2))
        with self.assertRaises(ValueError):
            self.g.setFrequency(1, 40e6)                    # above 30 MHz
        with self.assertRaises(ValueError):
            self.g.on(3)

    def test_limited_amplitude_is_an_error(self):
        self.g.setLoad(1, 50)
        self.assertEqual(self.g.outputState(1)['load'], 50.0)
        with self.assertRaisesRegex(InstrumentError, 'AMP: 15 asked, the generator has 10.0'):
            self.g.setAmplitude(1, 15)
        self.g.setLoad(1, 'HZ')
        self.g.setAmplitude(1, 15)

    def test_arb_burst_and_list(self):
        self.assertEqual(self.g.arbList(), {'M10': 'ExpFal', 'M2': 'StairUp'})
        self.g.arb(1, 'ExpFal', 500, 2, on=False)
        self.assertEqual(self.g.getWaveform(1), 'ARB')
        with self.assertRaisesRegex(InstrumentError, 'not found'):
            self.g.arb(1, 'Nothing')
        self.g.burst(1, 5)
        self.assertEqual(self.g.getMode(1), 'BURST')
        self.g.trigger(1)
        self.g.burstOff(1)
        self.assertEqual(self.g.getMode(1), '')
        self.assertIn('C1:BTWV MTRIG', self.srv.lines)


class Siglent(unittest.TestCase):
    """SPD1305X: setpoints read back, output state from SYST:STAT?, the extra empty line after an error answer."""

    def setUp(self):
        self.st = {'v': 3.3, 'a': 1.0, 'stat': 0, 'errors': ['-113,Undefined header,OUTPut?'], 'lose': 0}

        def answer(cmd):
            st = self.st
            if cmd == '*IDN?':
                return 'Siglent Technologies,SPD1305X,SPD13ECQA01701,2.1.2.12R3,V2.0'
            if cmd.startswith(('CH1:VOLT ', 'CH1:CURR ', 'OUTP CH1,')) and st['lose']:
                st['lose'] -= 1                              # a command lost by the supply
                return None
            if cmd.startswith('CH1:VOLT '):
                st['v'] = float(cmd.split()[1])
                return None
            if cmd.startswith('CH1:CURR '):
                st['a'] = float(cmd.split()[1])
                return None
            if cmd.startswith('OUTP CH1,'):
                st['stat'] = st['stat'] | 0x10 if cmd.endswith('ON') else st['stat'] & ~0x10
                return None
            if cmd == 'SYST:ERR?' or cmd == ':SYSTem:ERRor?':
                return (st['errors'].pop(0) + '\n') if st['errors'] else '+0, No error'
            on = bool(st['stat'] & 0x10)
            return {'CH1:VOLT?': f"{st['v']:.3f}", 'CH1:CURR?': f"{st['a']:.3f}", 'SYST:STAT?': hex(st['stat']),
                    'MEAS:VOLT?': f"{st['v'] * on:.3f}", 'MEAS:CURR?': f"{0.2 * on:.3f}",
                    'MEAS:POWE?': f"{st['v'] * 0.2 * on:.3f}", 'TIME:SET? CH1,2': '5.000,1.000,10,',
                    'IP?': '192.168.1.74', 'MASK?': '255.255.255.0', 'GATE?': '192.168.1.1',
                    'DHCP?': 'DHCP:OFF'}.get(cmd)
        self.srv = FakeScpi(answer)
        self.p = SIGLENT_SPD1305X('127.0.0.1', self.srv.port, timeout=1)
        self.p.WRITE_DELAY = 0

    def tearDown(self):
        self.p.close()
        self.srv.close()

    def test_setup_measure_off(self):
        self.assertEqual(self.p.checkModel(), 'SPD1305X')
        self.p.setup(12, 0.5)
        self.assertTrue(self.p.isOn())
        self.assertEqual(self.p.measureAll(), (12.0, 0.2, 2.4))
        self.assertEqual(self.p.waitVoltage(12.0, timeout=0.5), 12.0)
        self.assertEqual((self.p.getSetVoltage(), self.p.getSetCurrent()), (12.0, 0.5))
        self.p.off()
        self.assertFalse(self.p.status()['output'])
        with self.assertRaises(ValueError):
            self.p.setVoltage(31)                        # above the SPD1305X range

    def test_lost_commands_are_sent_again(self):
        self.st['lose'] = 1
        self.p.setVoltage(5)
        self.assertEqual(self.st['v'], 5.0)
        self.st['lose'] = 2
        with self.assertRaisesRegex(InstrumentError, 'did not take'):
            self.p.setCurrent(2)

    def test_errors_with_the_extra_empty_line(self):
        self.assertEqual(self.p.errors(), ['-113,Undefined header,OUTPut?'])
        self.assertEqual(self.p.getSetVoltage(), 3.3)    # the empty line did not shift the answers
        self.assertEqual(self.p.getTimer(2), (5.0, 1.0, 10.0))
        self.assertEqual(self.p.network()['dhcp'], 'OFF')
        self.st['stat'] = 0x01
        self.assertTrue(self.p.isCC())


class SerialTermTest(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()
        self.stop = False

        def console():                                               # echoes, answers, prints a prompt
            buf = b''
            while not self.stop:
                try:
                    buf += os.read(self.master, 100)
                except OSError:
                    return
                while b'\r\n' in buf:
                    line, buf = buf.split(b'\r\n', 1)
                    out = line + b'\r\n'
                    if line == b'VERSION?':
                        out += b'fw 1.2.3\r\n'
                    elif line == b'TEMP?':
                        out += b'temp=23.5 C\r\n'
                    elif line == b'SLOW':
                        time.sleep(0.05)
                        out += b'part1 '
                        os.write(self.master, out)
                        time.sleep(0.05)
                        out = b'part2 OK\r\n'
                    os.write(self.master, out + b'uut> ')
        threading.Thread(target=console, daemon=True).start()
        self.t = SerialTerm(os.ttyname(self.slave), prompt='uut> ', timeout=1.5, idle=0.3)

    def tearDown(self):
        self.stop = True
        self.t.close()
        os.close(self.slave)
        os.close(self.master)

    def test_cmd_echo_prompt_until_value(self):
        self.assertEqual(self.t.cmd('VERSION?'), 'fw 1.2.3')
        self.assertEqual(self.t.cmd('SLOW', until='OK'), 'part1 part2 OK')
        self.assertEqual(self.t.value('TEMP?'), 23.5)
        self.assertEqual(self.t.lines('VERSION?'), ['fw 1.2.3'])
        with self.assertRaises(TermError):
            self.t.cmd('NOTHING', until='NEVER', timeout=0.4)
        self.assertEqual(self.t.log[0], ('tx', 'VERSION?'))


class SshTermTest(unittest.TestCase):
    """A fake ``ssh`` / ``scp``: prints its argv and the askpass answer, exit code from the command."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ssh = os.path.join(self.dir, 'ssh')
        with open(self.ssh, 'w') as f:
            f.write('#!/usr/bin/env python3\nimport os, subprocess, sys, json\n'
                    'a = sys.argv[1:]\n'
                    'if "-O" in a: sys.exit(0)\n'
                    'cmd = a[a.index("--") + 1] if "--" in a else ""\n'
                    'pw = subprocess.run([os.environ["SSH_ASKPASS"]], capture_output=True, text=True).stdout.strip() '
                    'if os.environ.get("SSH_ASKPASS") else None\n'
                    'if cmd == "fail-ssh": print("ssh: connect to host x: refused", file=sys.stderr); sys.exit(255)\n'
                    'if cmd.startswith("exit "): sys.exit(int(cmd.split()[1]))\n'
                    'print(json.dumps({"argv": a, "pw": pw, "stdin": sys.stdin.read() if cmd.startswith("cat >") else ""}))\n')
        os.chmod(self.ssh, stat.S_IRWXU)

    def test_run_cmd_and_password_never_on_the_command_line(self):
        t = SshTerm('10.0.0.5', 'root', 's3cr3t', port=2222, ssh_bin=self.ssh)
        out = json.loads(t.cmd('uname -r'))
        self.assertEqual(out['pw'], 's3cr3t')                          # delivered through SSH_ASKPASS
        self.assertNotIn('s3cr3t', ' '.join(out['argv']))
        self.assertIn('root@10.0.0.5', out['argv'])
        self.assertEqual(out['argv'][:2], ['-p', '2222'])
        self.assertIn('StrictHostKeyChecking=no', out['argv'])
        self.assertIn('ControlMaster=auto', out['argv'])
        self.assertEqual(t.run('exit 3').code, 3)
        self.assertFalse(t.cmdOk('exit 1'))
        with self.assertRaises(SshError):
            t.cmd('exit 2')
        with self.assertRaises(SshError):
            t.run('fail-ssh')
        self.assertFalse(t.cmdOk('fail-ssh'))
        r = json.loads(t.run('cat > /tmp/x', stdin='hello').out)
        self.assertEqual(r['stdin'], 'hello')
        t.close()
        self.assertIsNone(t._dir)
        self.assertEqual(json.loads(t.cmd('again'))['pw'], 's3cr3t')    # usable after close()
        t.close()

    def test_key_auth_is_batch_mode(self):
        t = SshTerm('h', 'u', key='/k', ssh_bin=self.ssh, strict=True)
        argv = json.loads(t.cmd('true'))['argv']
        self.assertIn('BatchMode=yes', argv)
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('/k', argv)
        t.close()


class ParamFileTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_ini_types_order_comments(self):
        p = os.path.join(self.dir, 'cal.ini')
        with open(p, 'w') as f:
            f.write('# calibration\n[main]\ngain = 1.0\nname = st 1\n')
        pf = ParamFile(p)
        self.assertFalse(pf.create({'x': 1}))                          # exists: untouched
        self.assertEqual(pf.all(), {'gain': 1.0, 'name': 'st 1'})
        pf.set('gain', 1.25)
        pf.setMany({'offset': -0.01, 'enabled': True, 'code': '007', 'empty': None})
        self.assertEqual(pf.get('gain'), 1.25)
        self.assertEqual((pf.get('enabled'), pf.get('code'), pf.get('empty'), pf.get('nope', 5)), (True, '007', None, 5))
        self.assertEqual(pf.increment('count'), 1)
        self.assertEqual(pf.increment('count', 2), 3)
        self.assertTrue(pf.delete('name'))
        self.assertFalse(pf.delete('name'))
        text = pf.readText()
        self.assertTrue(text.startswith('# calibration\n[main]\ngain = 1.25'))
        self.assertIn('code = "007"', text)
        for bad in ('a=b', '', ' x', 'a#'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pf.set(bad, 1)

    def test_json_and_text(self):
        pf = ParamFile(os.path.join(self.dir, 'sub', 'state.json'))
        self.assertTrue(pf.create({'boards': 0}))
        pf.set('last', 'SN-1')
        self.assertEqual(pf.increment('boards'), 1)
        with open(pf.path) as f:
            self.assertEqual(json.load(f), {'boards': 1, 'last': 'SN-1'})
        log = ParamFile(os.path.join(self.dir, 'log.csv'))
        log.appendLine('sn,result')
        log.appendLine('SN-1,PASS\n')
        self.assertEqual(log.readText(), 'sn,result\nSN-1,PASS')

    def test_relative_paths_are_under_testplatform(self):
        self.assertEqual(ParamFile('data/x.ini').path, os.path.join(ROOT, 'testPlatform', 'data', 'x.ini'))
        self.assertEqual([parse_value(v) for v in ('12', '1.5', 'yes', '', '"x"', 'abc')], [12, 1.5, True, None, 'x', 'abc'])
        self.assertEqual(format_value(' a'), '" a"')


class SiglentScope(unittest.TestCase):
    """SDS802X HD: ripple setup with read-back, simple measurements ("****" = None), WORD waveform, raw PNG."""

    def setUp(self):
        self.state = {':CHANnel1:COUPling': 'DC', ':CHANnel1:SCALe': '1.00E+00', ':TIMebase:SCALe': '1.00E-03',
                      ':CHANnel1:PROBe': '1.00E+01', ':MEASure': 'OFF'}
        pre = bytearray(346)
        pre[0:8] = b'WAVEDESC'
        struct.pack_into('<i', pre, 116, 4)                      # 4 points
        struct.pack_into('<fff', pre, 156, 0.05, 0.01, 7680.0)   # V/div, offset, codes per div
        struct.pack_into('<f', pre, 176, 1e-9)                   # sample interval
        struct.pack_into('<d', pre, 180, 0.0)                    # delay
        struct.pack_into('<f', pre, 328, 1.0)                    # probe
        self.pre = bytes(pre)

        def answer(cmd):
            if cmd == '*IDN?':
                return 'Siglent Technologies,SDS802X HD,SDS08A0000,4.8.12.1.1.6.5'
            if cmd == ':CHANnel1:PROBe VALue,1':
                self.state[':CHANnel1:PROBe'] = '1.00E+00'
                return None
            if cmd.endswith('?') and cmd[:-1] in self.state:
                return self.state[cmd[:-1]]
            if ' ' in cmd and not cmd.endswith('?') and cmd.split(' ')[0] in self.state:
                key, val = cmd.split(' ', 1)
                self.state[key] = val if not val[0].isdigit() else f'{float(val):.2E}'
                return None
            if cmd.startswith(':MEASure:SIMPle:VALue? '):
                if self.state[':MEASure'] != 'ON':
                    return 'The number of measurements is zero'
                return {'PKPK': '2.5E-02', 'FREQ': '****'}.get(cmd.split()[-1], '1.0E+00')
            if cmd == ':WAVeform:PREamble?':
                return block(self.pre)
            if cmd == ':WAVeform:DATA?':
                return block(struct.pack('<4h', 0, 7680, -7680, 3840))
            if cmd == ':PRINt? PNG':
                return PNG + b'IEND\xaeB`\x82'
            if cmd == ':SYSTem:ERRor?':
                return '0,"No error"'
            if cmd.endswith('?'):
                return '1'
            return None
        self.srv = FakeScpi(answer)
        self.s = SIGLENT_SDS802XHD('127.0.0.1', self.srv.port, timeout=2)
        self.s.SETTLE = 0

    def tearDown(self):
        self.s.close()
        self.srv.close()

    def test_model_and_channels(self):
        self.assertEqual(self.s.checkModel(), 'SDS802X HD')
        with self.assertRaises(ValueError):
            self.s.setScale(3, 0.1)                              # a 2-channel model

    def test_ripple_setup_reads_back(self):
        self.s.setupRipple(1)
        self.assertEqual((self.state[':CHANnel1:COUPling'], self.state[':CHANnel1:PROBe']), ('AC', '1.00E+00'))
        self.assertEqual(float(self.state[':CHANnel1:SCALe']), 0.05)
        self.assertEqual(float(self.state[':TIMebase:SCALe']), 5e-6)
        self.assertIn(':TRIGger:MODE AUTO', self.srv.lines)
        self.state[':CHANnel1:COUPling'] = 'DC'
        self.srv.lines.clear()
        orig = self.s.setCoupling
        self.s.setCoupling = lambda ch, c: None                  # the scope "does not take" the coupling
        with self.assertRaisesRegex(InstrumentError, 'ripple setup CH1'):
            self.s.setupRipple(1)
        self.s.setCoupling = orig

    def test_measurements(self):
        self.assertEqual(self.s.getVoltPkPk(1), 0.025)          # switches the measurement on first
        self.assertIn(':MEASure ON', self.srv.lines)
        self.assertIn(':MEASure:SIMPle:SOURce C1', self.srv.lines)
        self.assertIsNone(self.s.getFrequency(1))               # "****"
        self.assertEqual(self.s.getRipple(1, n=3, delay=0), 0.025)
        self.assertEqual(self.s.measureStats('PKPK', 1, n=2, delay=0), (0.025, 0.025, 0.025))

    def test_waveform_and_screenshot(self):
        t, v = self.s.getWaveform(1, points=4)
        self.assertEqual([round(x, 4) for x in v], [-0.01, 0.04, -0.06, 0.015])
        self.assertAlmostEqual(t[1] - t[0], 1e-9)
        self.assertIn(':WAVeform:WIDTh WORD', self.srv.lines)
        with tempfile.TemporaryDirectory() as d:
            path = self.s.screenshot(os.path.join(d, 's.png'))
            with open(path, 'rb') as f:
                data = f.read()
        self.assertTrue(data.startswith(b'\x89PNG') and data.endswith(b'IEND\xaeB`\x82'))
        self.assertEqual(self.s.idn().split(',')[1], 'SDS802X HD')   # nothing left in the socket


if __name__ == '__main__':
    unittest.main()
