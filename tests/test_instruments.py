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


if __name__ == '__main__':
    unittest.main()
