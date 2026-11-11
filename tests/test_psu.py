"""testPlatform/instruments/psu_custom6020.py and psu_custom305.py against a fake controller on localhost (one TCP connection per command, like the real
one) — the real power supply is never contacted."""
import os
import socket
import sys
import threading
import unittest

from tests.support import ROOT

sys.path.insert(0, os.path.join(ROOT, 'testPlatform'))
from instruments.psu_custom6020 import PSU_CUSTOM6020, PsuError  # noqa: E402
from instruments.psu_custom305 import PSU_CUSTOM305  # noqa: E402

DATA = ('12.00,12.01,0.090,28,12.00,1.000,0.40,1,0,1,0.00,0.00,-0.000,27,0.00,1.000,0.00,1,0,1,0,'
        '23.64,25858,139,23.61,24832,119,0,0,15.00,0,1,0,0,15.00,0,1')


class FakePsu:
    """Answers like the controller and closes the connection after every answer."""

    def __init__(self):
        self.received = []
        self.state = {'OUT1': '0', 'VOLT1': '0.00'}
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _answer(self, cmd):
        if cmd == 'GET_PSU_DATA':
            return DATA
        if cmd == '*IDN?':
            return 'Device: SAMD21, MultichannelCerPsu\nVersion: 2.90\nBuild: Nov  3 2026, 0001'
        if cmd.startswith('VOLT:1:'):
            self.state['VOLT1'] = cmd.split(':')[2]
            return f'OK: Channel 1 voltage preset set to {self.state["VOLT1"]}'
        if cmd == 'VOLT:1?':
            return self.state['VOLT1']
        if cmd.startswith('VOLT:3'):
            return 'ERROR: Invalid channel number'
        if cmd.startswith('OUT:1:'):
            self.state['OUT1'] = cmd[-1]
            return 'OK: Channel 1 output set to ' + cmd[-1]
        if cmd == 'STATUS:1?':
            return self.state['OUT1']
        if cmd.startswith('CURR:1:'):
            return 'OK'
        if cmd == 'RESET':
            return 'OK: All outputs turned off'
        if cmd == 'ADC:MEAS:EXT1:ALL?1':
            return 'INA228,12.0148,0.0915,1.0998'
        if cmd == 'EXTIO:LIST?':
            return '1|MIX|25|Jig Controller|K1|K2\n2|IN|21|Inputs|'
        if cmd == 'EXTIO:OUT:ALL 1,00FF':
            return '00FF'
        if cmd == 'GET_DEVICE_ID':
            return 'MultichannelCerPsu|0001'
        canned = {
            'REG?:1:0:2': 'Reg 0x0(0): 0x4b0(1200)\nReg 0x1(1): 0x64(100)',
            'REG?:1:5:1:3:9600': 'Reg 0x5(5): 0x1(1)',
            'ADC:MEAS:ONBOARD?0,1': '12.4800,6326',
            'ADC:MEAS:EXT1:VI?': '12.0150,0.0900',
            'ADC:MEAS:EXT1:AMP?': '0.0904',
            'ADC:MEAS:EXT2:ALL?0': 'ADS1115,3.3000,17600',
            'ADC:CALL:ONBOARD:DATA?': '0,0,0.0001972206,791\n0,1,0.0031305149,9',
            'ADC:CALL:EXT1:DATA?': '0.0001880000,12,0.0031000000,14',
            'EXTIO:STATE?': '1|MIX|25|1|0002|0000\n2|IN|21|0|0000|0000',
            'EXTIO:STATE? 1': '1|MIX|25|1|0102|0100',
            'EXTIO:OUT? 1,8': '1',
            'SOUR:I2C:SCAN?': '25,40,41',
            'SOUR:I2C:READ? 41,00,02': 'C3,40',
            'GET_DEVICE_INFO': '192.168.1.91 DE:AD:BE:2F:2E:ED,80,8080,2.90,1,2,3,4,READY',
            'SYST:RESET?': '33',
            'SYST:LOG:INFO?': '64,0,512',
            'SYST:LOG? 0,2': '63,18,5,16,33,0\n62,18,0,1,0,1',
            'HW:VER?': '1.0.0',
            'BLK:1?': '2',
            'STATUS': 'OK: Device is in config mode',
        }
        if cmd in canned:
            return canned[cmd]
        if cmd.startswith(('EXTIO:ADD ', 'EXTIO:EDIT ', 'EXTIO:DEL ', 'EXTIO:CLEAR', 'SOUR:I2C:WRITE ', 'BLK:1:',
                           'VCORR:', 'REG:', 'OVP:', 'OCP:', 'SWOCP:', 'ADC:CALL', 'CALL:', 'SET_REF', 'CLEAR_CALL')):
            return 'OK:3' if cmd.startswith('EXTIO:ADD') else 'OK'
        return 'ERROR: Undefined command'

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b''
                while not data.endswith(b'\r\n'):
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                cmd = data.decode().rstrip('\r\n')
                self.received.append(cmd)
                conn.sendall(self._answer(cmd).encode() + b'\r\n')

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)      # wakes the accept() of the server thread
        except OSError:
            pass
        self.sock.close()


class Psu(unittest.TestCase):
    def setUp(self):
        self.fake = FakePsu()
        self.psu = PSU_CUSTOM6020('127.0.0.1', self.fake.port, timeout=2)

    def tearDown(self):
        self.fake.close()

    def test_commands_on_the_wire(self):
        self.psu.setup(1, 12, 0.5)
        self.assertEqual(self.fake.received, ['VOLT:1:12.00', 'CURR:1:0.500', 'OUT:1:1'])
        self.assertTrue(self.psu.isOn(1))
        self.assertEqual(self.psu.getVoltage(1), 12.0)
        self.psu.off(1)
        self.assertFalse(self.psu.isOn(1))
        self.psu.allOff()
        self.assertEqual(self.fake.received[-1], 'RESET')

    def test_errors(self):
        with self.assertRaises(PsuError):
            self.psu.query('VOLT:3?')
        with self.assertRaises(PsuError):
            self.psu.query('BOGUS')
        with self.assertRaises(ValueError):
            self.psu.getVoltage(3)
        with self.assertRaises(ValueError):
            self.psu.query('OUT:1:1\r\nRESET')                      # one command per call
        self.fake.close()
        with self.assertRaises(PsuError):
            PSU_CUSTOM6020('127.0.0.1', self.fake.port, timeout=0.5, retries=2).getVoltage(1)

    def test_data_and_modules(self):
        d = self.psu.getData()
        self.assertEqual((d[1]['voltage'], d[1]['current'], d[1]['set_current']), (12.0, 0.09, 1.0))
        self.assertTrue(d[1]['cv'] and d[1]['online'] and d[2]['online'])
        self.assertFalse(d[1]['cc'])
        self.assertEqual(d[1]['input_voltage'], 23.64)
        self.assertEqual(d[1]['ocp_limit'], 15.0)
        self.assertEqual(self.psu.extMeasure(1), {'type': 'INA228', 'voltage': 12.0148, 'current': 0.0915, 'power': 1.0998})
        mods = self.psu.ioList()
        self.assertEqual([(m['n'], m['type'], m['name']) for m in mods], [(1, 'MIX', 'Jig Controller'), (2, 'IN', 'Inputs')])
        self.assertEqual(self.psu.ioOutAll(1, 0xFF), 0xFF)
        self.assertEqual(self.psu.deviceId(), ('MultichannelCerPsu', '0001'))
        self.assertIn('Version: 2.90', self.psu.identify())

    def test_psu_module_and_dmm(self):
        self.assertEqual(self.psu.regRead(1, 0, 2), [1200, 100])
        self.assertEqual(self.psu.regRead(1, 5, 1, slave=3, baud=9600), [1])
        self.psu.regWrite(1, 0, 1200)
        self.assertEqual(self.fake.received[-1], 'REG:1:0:1200')
        self.assertEqual(self.psu.getBacklight(1), 2)
        self.psu.setBacklight(1, 5)
        self.assertEqual(self.fake.received[-1], 'BLK:1:5')
        with self.assertRaises(ValueError):
            self.psu.setBacklight(1, 9)
        self.psu.setKelvin(1, True)
        self.assertEqual(self.fake.received[-1], 'VCORR:1:1')
        self.assertEqual(self.psu.onboardRaw(0, 1), (12.48, 6326))
        self.assertEqual(self.psu.onboardVoltage(0), 12.48)
        with self.assertRaises(ValueError):
            self.psu.onboardVoltage(4)
        self.assertEqual(self.psu.extVI(1), (12.015, 0.09))
        self.assertEqual(self.psu.extCurrent(1), 0.0904)
        self.assertEqual(self.psu.extMeasure(2, 0), {'type': 'ADS1115', 'voltage': 3.3, 'raw': 17600})

    def test_calibration_commands(self):
        self.assertEqual(self.psu.onboardCalData()[1], {'ch': 0, 'range': 1, 'factor': 0.0031305149, 'zero': 9})
        self.assertEqual(self.psu.extCalData(1), {'gain0': 0.000188, 'zero0': 12, 'gain1': 0.0031, 'zero1': 14})
        self.psu.setOnboardFactor(0, 1, 0.0031305)
        self.psu.extCalZero(1, 1)
        self.psu.extCalibrate(2, 1, 24)
        self.psu.extCalibrateWithPsu(1, 0)
        self.psu.setRefVoltage(5.109)
        self.assertEqual(self.fake.received[-5:], ['ADC:CALLSET: 0 1 0.0031305000', 'ADC:CALL:EXT1:ZERO?1',
                                                   'ADC:CALL:EXT2?1,24.0000', 'CALL:1:0', 'SET_REF_VOLTAGE 5.109'])

    def test_extio_cards(self):
        states = self.psu.ioStates()
        self.assertEqual([(m['n'], m['online'], m['pins']) for m in states], [(1, True, 2), (2, False, 0)])
        self.assertEqual(self.psu.ioPin(1, 8), 1)
        self.assertEqual(self.psu.ioPin(1, 0), 0)
        self.assertEqual(self.psu.ioOutRead(1, 8), 1)
        self.assertEqual(self.psu.ioAdd('out', 0x21, 'Relays', ['K1', 'K2']), 3)
        self.assertEqual(self.fake.received[-1], 'EXTIO:ADD OUT|21|Relays|K1|K2')
        self.psu.ioEdit(1, 'MIX', '25', 'Jig')
        self.assertEqual(self.fake.received[-1], 'EXTIO:EDIT 1|MIX|25|Jig')
        self.psu.ioDelete(2)
        self.psu.ioClear()
        self.assertEqual(self.fake.received[-2:], ['EXTIO:DEL 2', 'EXTIO:CLEAR'])
        for bad in (('BAD', 0x21, 'x'), ('IN', 0x21, 'a|b'), ('IN', 0x21, 'a;b')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.psu.ioAdd(*bad)

    def test_i2c(self):
        self.assertEqual(self.psu.i2cScan(), [0x25, 0x40, 0x41])
        self.assertEqual(self.psu.i2cRead(0x41, 0, 2), [0xC3, 0x40])
        self.psu.i2cWrite(0x41, 1, [0xC3, 0x83])
        self.assertEqual(self.fake.received[-1], 'SOUR:I2C:WRITE 41,01,C3,83')
        with self.assertRaises(ValueError):
            self.psu.i2cRead(0x41, 0, 33)

    def test_device_and_log(self):
        self.assertEqual(self.psu.firmwareVersion(), '2.90')
        self.assertEqual(self.psu.hwVersion(), '1.0.0')
        info = self.psu.deviceInfo()
        self.assertEqual((info['ip'], info['ports'], info['firmware'], info['status']), ('192.168.1.91', (80, 8080), '2.90', 'READY'))
        self.assertEqual(info['uptime_s'], ((1 * 24 + 2) * 60 + 3) * 60 + 4)
        self.assertTrue(self.psu.ping())
        self.assertEqual(self.psu.resetCause(), 'power-on, watchdog')
        self.assertEqual(self.psu.logInfo(), {'entries': 64, 'lost': 0, 'capacity': 512})
        log = self.psu.log(2)
        self.assertEqual([(e['seq'], e['event']) for e in log], [(63, 'EXT_IO no response'), (62, 'Boot')])

    def test_wait_voltage(self):
        self.psu.setVoltage(1, 5)
        self.assertEqual(self.psu.waitVoltage(1, 5.0, 0.1, timeout=1), 5.0)



class FakePsu305(FakePsu):
    """PSU Ethernet Controller FW 2.0: setpoints / OUTP ON only with REM on, answers OK."""

    def __init__(self):
        super().__init__()
        self.state = {'rem': 0, 'out': 0, 'v': 0.0, 'a': 0.0, 'dout': 0}

    def _answer(self, cmd):
        st = self.state
        up = cmd.upper()
        if up == 'SYST:REM ON':
            st.update(rem=1, out=0)
            return 'OK'
        if up in ('SYST:REM OFF', 'SYST:LOC'):
            st.update(rem=0, out=0)
            return 'OK'
        if up.startswith(('VOLT ', 'CURR ', 'APPL ', 'OUTP ', '*RST')):
            if not st['rem']:
                return 'ERROR: -221,Settings conflict; REM off, the supply is under front panel control'
            if up.startswith('APPL '):
                v, a = up[5:].split(',')
                st.update(v=float(v), a=float(a))
            elif up.startswith('OUTP '):
                st['out'] = 1 if up.endswith('ON') else 0
            return 'OK'
        canned = {
            '*IDN?': 'PSU-ETH,PSU-ETH,0,FW 2.0 Oct 31 2026', 'SYST:REM?': str(st['rem']), 'OUTP?': str(st['out']),
            'MEAS:ALL?': f"{st['v'] * st['out']:.4f},0.1000,{st['v'] * st['out'] * 0.1:.3f}",
            'MEAS:VOLT?': f"{st['v'] * st['out']:.4f}", 'VOLT:LIM?': '60.0000', 'CURR:LIM?': '5.0000',
            'PSU:DATA?': '0.0026,0.0044,0.000,0.0000,0.0000,0,0,1,1,0,7,60.0000,5.0000,IDLE',
            'DIG:INP?': '7', 'DIG:INP? 2': '1', 'DIG:OUTP?': str(st['dout']),
            'EXTIO:LIST?': '1|MIX|25|IO module|K1|K2', 'EXTIO:OUT 1,3,1': '1',
            'SYST:INFO?': 'fw=2.0\nreset=power-on', 'SYST:ERR?': '0,"No error"', '*TST?': '0',
        }
        if up.startswith('DIG:OUTP '):
            n, v = up[9:].split(',')
            st['dout'] = st['dout'] | (1 << (int(n) - 1)) if v == '1' else st['dout'] & ~(1 << (int(n) - 1))
            return 'OK'
        return canned.get(up, 'ERROR: -113,Undefined header')


class Psu305(unittest.TestCase):
    def setUp(self):
        self.fake = FakePsu305()
        self.psu = PSU_CUSTOM305('127.0.0.1', self.fake.port, timeout=2)

    def tearDown(self):
        self.fake.close()

    def test_auto_remote_setup_and_measure(self):
        self.psu.setup(12, 0.5)
        self.assertEqual(self.fake.received, ['APPL 12.0000,0.5000', 'SYST:REM ON', 'APPL 12.0000,0.5000', 'OUTP ON'])
        self.assertTrue(self.psu.isRemote() and self.psu.isOn())
        self.assertEqual(self.psu.measureAll(), (12.0, 0.1, 1.2))
        self.assertEqual(self.psu.waitVoltage(12.0, timeout=0.5), 12.0)
        self.psu.off()
        self.psu.local()
        self.assertFalse(self.psu.isRemote())
        self.fake.received.clear()
        self.psu.off()                                   # without REM nothing is sent but the query
        self.assertEqual(self.fake.received, ['SYST:REM?'])

    def test_without_auto_remote_the_refusal_is_raised(self):
        psu = PSU_CUSTOM305('127.0.0.1', self.fake.port, timeout=2, auto_remote=False)
        with self.assertRaisesRegex(PsuError, '-221'):
            psu.setVoltage(5)
        with self.assertRaisesRegex(PsuError, '-113'):
            psu.query('BOGUS?')

    def test_data_io_and_info(self):
        d = self.psu.getData()
        self.assertEqual((d['dig_in'], d['v_max'], d['remote'], d['cal']), (7, 60.0, False, 'IDLE'))
        self.assertEqual(self.psu.getLimits(), (60.0, 5.0))
        self.assertEqual((self.psu.digIn(), self.psu.digIn(2)), (7, 1))
        self.psu.digOut(2, 1)
        self.assertEqual(self.psu.digOutRead(), 2)
        with self.assertRaises(ValueError):
            self.psu.digOut(4, 1)
        self.assertEqual(self.psu.ioList(), [{'n': 1, 'type': 'MIX', 'addr': '25', 'name': 'IO module',
                                              'labels': ['K1', 'K2']}])
        self.assertEqual(self.psu.ioOut(1, 3, 1), 1)
        self.assertEqual(self.psu.info(), {'fw': '2.0', 'reset': 'power-on'})
        self.assertEqual(self.psu.errors(), [])
        self.assertTrue(self.psu.selfTest())



if __name__ == '__main__':
    unittest.main()
