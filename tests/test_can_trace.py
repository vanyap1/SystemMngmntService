"""HW Utils → CAN: trace files (core/can_trace.py), recording and the player of net.CanBus — no CAN socket needed."""
import io
import os
import shutil
import time
import unittest

from tests.support import client, config
from core import can_trace, net


def _root():
    return config.can_traces_dir()


class _FakeSock:
    def close(self):
        pass


def _bus():
    bus = net.CanBus('vcan-test')
    bus._sock = _FakeSock()     # "open": touch() never opens a real socket, sends are patched
    return bus


def _wait(pred, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(_root(), ignore_errors=True)
        os.makedirs(_root())

    def write(self, rel, text):
        path = os.path.join(_root(), rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)
        return path


class Format(unittest.TestCase):
    def test_round_trip(self):
        frames = [
            {'t': 1700000000.123456, 'dir': 'rx', 'can_id': 0x123, 'ext': False, 'rtr': False, 'dlc': 3, 'data': '0a0b0c'},
            {'t': 1700000000.5, 'dir': 'tx', 'can_id': 0x18FF50E5, 'ext': True, 'rtr': False, 'dlc': 0, 'data': ''},
            {'t': 1700000001.0, 'dir': 'rx', 'can_id': 0x7FF, 'ext': False, 'rtr': True, 'dlc': 2, 'data': ''},
            {'t': 1700000002.0, 'dir': 'err', 'can_id': 0x20, 'ext': False, 'rtr': False, 'dlc': 8, 'data': '00' * 8},
        ]
        lines = [can_trace.format_line(dict(f, error=''), 'can0') for f in frames]
        self.assertEqual(lines[0], '(1700000000.123456) can0 123#0A0B0C\n')
        self.assertEqual(lines[1], '(1700000000.500000) can0 18FF50E5# T\n')
        self.assertEqual(lines[2], '(1700000001.000000) can0 7FF#R2\n')
        self.assertEqual(lines[3], '(1700000002.000000) can0 20000020#0000000000000000\n')
        for f, line in zip(frames, lines):
            got = can_trace.parse_line(line)
            self.assertAlmostEqual(got.pop('t'), f['t'], places=6)
            self.assertEqual(got, {k: v for k, v in f.items() if k != 't'})

    def test_candump_lines_and_junk(self):
        self.assertEqual(can_trace.parse_line('(1.5) vcan0 00000123#11')['ext'], True)
        self.assertEqual(can_trace.parse_line('(1.000001) can1 5A1#R')['dlc'], 0)
        for line in ['# comment', '', 'garbage', '(1.0) can0 123#1', '(1.0) can0 123#' + '00' * 9, '(1.0) can0 123#zz']:
            with self.subTest(line=line):
                self.assertIsNone(can_trace.parse_line(line))


class Store(Base):
    def test_tree_and_paths(self):
        self.write('a.log', '')
        self.write('dir/sub/b.log', '')
        self.write('dir/notes.txt', '')
        self.write('.trash/old.log', '')
        tree = can_trace.tree()
        self.assertEqual([n['name'] for n in tree], ['dir', 'a.log'])
        self.assertEqual(tree[0]['children'][0]['children'][0]['path'], 'dir/sub/b.log')
        for bad in ['../x.log', '.hidden.log', 'a/../../x.log', 'x.txt', 'a;b.log', '', '1/2/3/4/x.log']:
            with self.subTest(bad=bad):
                with self.assertRaises(can_trace.TraceError):
                    can_trace.check_path(bad)

    def test_mkdir_rename_delete(self):
        self.assertEqual(can_trace.mkdir('dir'), 'dir')
        with self.assertRaises(can_trace.TraceError):
            can_trace.mkdir('dir')
        self.write('dir/a.log', 'x')
        self.write('dir/b.log', 'y')
        self.assertEqual(can_trace.rename('dir/a.log', 'c'), 'dir/c.log')      # extension kept
        with self.assertRaises(can_trace.TraceError):
            can_trace.rename('dir/c.log', 'b.log')                             # exists
        self.assertEqual(can_trace.rename('dir', 'bench'), 'bench')
        can_trace.delete('bench/b.log')
        self.assertFalse(os.path.exists(os.path.join(_root(), 'bench/b.log')))
        trash = os.listdir(os.path.join(_root(), '.trash'))
        self.assertEqual(len(trash), 1)
        self.assertTrue(trash[0].endswith('bench_b.log'))
        can_trace.delete('bench')
        self.assertEqual(can_trace.tree(), [])

    def test_upload(self):
        good = b'(1700000000.000000) can0 123#11\n'
        self.assertEqual(can_trace.save_upload('', 'trace.log', io.BytesIO(good)), 'trace.log')
        self.assertEqual(can_trace.save_upload('', 'other', io.BytesIO(good)), 'other.log')
        with self.assertRaises(can_trace.TraceError):
            can_trace.save_upload('', 'trace.log', io.BytesIO(good))           # no overwrite
        with self.assertRaises(can_trace.TraceError):
            can_trace.save_upload('', 'bad.log', io.BytesIO(b'hello world\nnot a trace\n'))
        self.assertFalse(os.path.exists(os.path.join(_root(), 'bad.log')))
        self.assertFalse([n for n in os.listdir(_root()) if n.endswith('.part')])


class Recording(Base):
    def test_record_new_and_append(self):
        bus = _bus()
        bus.record_start('bench/run.log')
        with self.assertRaises(net.NetError):
            bus.record_start('x.log')                                          # one at a time
        with bus._lock:
            bus._record('rx', 0x123, 2, b'\x01\x02', t=100.0)
            bus._record('tx', 0x18FF50E5 | net.CAN_EFF_FLAG, 0, b'', t=100.5)
            bus._record('rp', 0x555, 1, b'\x01', t=100.6)                      # replayed: not recorded
        self.assertEqual(bus.frames()['rec']['frames'], 2)
        bus.record_stop()
        d = bus.frames()
        self.assertIsNone(d['rec'])
        self.assertEqual(d['rec_last']['frames'], 2)
        with self.assertRaises(net.NetError):
            bus.record_start('bench/run.log')                                  # exists: append only
        bus.record_start('bench/run.log', append=True)
        with bus._lock:
            bus._record('rx', 0x123, 2, b'\x03\x04', t=200.0)
        bus.record_stop()
        with open(os.path.join(_root(), 'bench/run.log')) as f:
            lines = f.read().splitlines()
        self.assertEqual([ln for ln in lines if not ln.startswith('#')],
                         ['(0000000100.000000) vcan-test 123#0102', '(0000000100.500000) vcan-test 18FF50E5# T',
                          '(0000000200.000000) vcan-test 123#0304'])
        self.assertEqual(sum(ln.startswith('#') for ln in lines), 2)          # one header per session
        with self.assertRaises(net.NetError):
            bus.record_start('missing.log', append=True)

    def test_close_stops_recording(self):
        bus = _bus()
        bus.record_start('a.log')
        with bus._lock:
            bus._close()
        self.assertIsNone(bus.frames()['rec'])


TRACE = ''.join(f'({1000 + i * 0.01:.6f}) can0 {0x100 + i % 3:03X}#{i:02X} \n' for i in range(30)) + \
        '# recording 2 (a gap of hours follows: not waited for)\n' + \
        '(9000.000000) can0 20000020#0000000000000000\n(9000.010000) can0 7FF#R1\n'


class Player(Base):
    def test_view_mode(self):
        self.write('t.log', TRACE)
        bus = _bus()
        bus.play_start('t.log', 'view', speed=10)
        self.assertTrue(_wait(lambda: bus.frames()['play'] is None))
        d = bus.frames()
        self.assertTrue(d['play_last']['done'])
        self.assertEqual(d['play_last']['frames'], 32)
        self.assertEqual(d['totals']['rp'], 32)
        self.assertEqual({f['dir'] for f in d['frames']}, {'rp'})
        self.assertIn('no ACK', [f['error'] for f in d['frames']][-2])
        self.assertLess(d['play_last']['elapsed'], 1)                          # the gap was skipped

    def test_bus_mode_sends_and_skips_errors(self):
        self.write('t.log', TRACE)
        bus = _bus()
        sent = []
        bus._send_raw = lambda raw, dlc, payload: sent.append((raw, dlc, payload))
        bus.play_start('t.log', 'bus', speed=10)
        self.assertTrue(_wait(lambda: bus.frames()['play'] is None))
        self.assertEqual(len(sent), 31)
        self.assertEqual(sent[0], (0x100, 1, b'\x00'))
        self.assertEqual(sent[-1], (0x7FF | net.CAN_RTR_FLAG, 1, b''))

    def test_pause_speed_stop(self):
        self.write('t.log', TRACE)
        bus = _bus()
        bus.play_start('t.log', 'view', speed=0.1)
        self.assertTrue(_wait(lambda: bus.frames()['play']['frames'] >= 1))
        bus.play_control('pause')
        time.sleep(0.15)
        n = bus.frames()['play']['frames']
        time.sleep(0.3)
        self.assertEqual(bus.frames()['play']['frames'], n)
        with self.assertRaises(net.NetError):
            bus.play_control('set', speed=1000)
        bus.play_control('set', speed=4, loop=True)
        self.assertEqual((bus.frames()['play']['speed'], bus.frames()['play']['loop']), (4, True))
        bus.play_control('resume')
        bus.play_control('stop')
        self.assertTrue(_wait(lambda: bus.frames()['play'] is None))
        self.assertFalse(bus.frames()['play_last']['done'])
        with self.assertRaises(net.NetError):
            bus.play_control('pause')

    def test_loop_and_stop_tx(self):
        self.write('t.log', TRACE)
        bus = _bus()
        bus._send_raw = lambda *a: None
        bus.play_start('t.log', 'bus', speed=100, loop=True)
        self.assertTrue(_wait(lambda: (bus.frames()['play'] or {}).get('loops', 0) >= 1))
        bus.stop_tx()                                                           # a test script starts
        self.assertTrue(_wait(lambda: bus.frames()['play'] is None))

    def test_refusals(self):
        self.write('t.log', TRACE)
        bus = _bus()
        with self.assertRaises(can_trace.TraceError):
            bus.play_start('missing.log')
        with self.assertRaises(net.NetError):
            bus.play_start('t.log', 'loud')
        bus.record_start('t2.log')
        with self.assertRaises(net.NetError):
            bus.play_start('t2.log')                                            # being recorded
        bus.record_stop()
        closed = net.CanBus('vcan-test')
        closed._open = lambda: None
        with self.assertRaises(net.NetError):
            closed.play_start('t.log')


class FileView(Base):
    def test_scan_and_pages(self):
        lines = []
        for i in range(2500):
            if i == 1500:
                lines.append('# recording 2\n')
            t = 1000 + i * 0.01 + (5000 if i >= 1500 else 0)          # hours later: gap not counted
            lines.append(f'({t:.6f}) can0 {0x100 + i % 3:03X}#{i % 256:02X}{" T" if i % 3 == 2 else ""}\n')
        lines.append('(6025.000000) can0 20000020#0000000000000000\n')
        self.write('big.log', ''.join(lines))
        path = os.path.join(_root(), 'big.log')
        info, index = can_trace.scan(path)
        self.assertEqual((info['frames'], info['sessions'], len(index)), (2501, 1, 3))
        self.assertEqual([r['key'] for r in info['ids']], ['s:100', 's:101', 's:102', 'err'])
        self.assertEqual((info['ids'][2]['tx'], info['ids'][2]['rx']), (833, 0))
        # a page that starts on an index entry right after the session comment
        page = can_trace.read_frames('big.log', 1500, 3)
        self.assertEqual([f['n'] for f in page['frames']], [1500, 1501, 1502])
        whole = can_trace.read_frames('big.log', 1490, 20)['frames']
        self.assertEqual(page['frames'][0]['rel'], whole[10]['rel'])
        self.assertAlmostEqual(whole[10]['rel'] - whole[9]['rel'], 0.0)      # session jump not counted
        self.assertAlmostEqual(whole[11]['rel'] - whole[10]['rel'], 0.01)
        self.assertAlmostEqual(info['duration'], whole[10]['rel'] + 1000 * 0.01, places=6)
        page = can_trace.read_frames('big.log', 10, 5, key='s:101')
        self.assertEqual(page['total'], 833)
        self.assertEqual([f['n'] for f in page['frames']], [31, 34, 37, 40, 43])
        self.assertEqual(can_trace.read_frames('big.log', 0, 5, key='err')['frames'][0]['dir'], 'err')
        with self.assertRaises(can_trace.TraceError):
            can_trace.read_frames('big.log', 0, 5, key='s:xyz')

    def test_cache_follows_changes(self):
        path = self.write('a.log', '(1.0) can0 123#01\n')
        self.assertEqual(can_trace.scan(path)[0]['frames'], 1)
        with open(path, 'a') as f:
            f.write('(2.0) can0 124#02\n')
        self.assertEqual(can_trace.scan(path)[0]['frames'], 2)

    def test_replay_skips_ids(self):
        self.write('t.log', TRACE)
        bus = _bus()
        sent = []
        bus._send_raw = lambda raw, dlc, payload: sent.append(raw)
        with self.assertRaises(can_trace.TraceError):
            bus.play_start('t.log', 'bus', speed=10, skip=['bad key'])
        bus.play_start('t.log', 'bus', speed=10, skip=['s:100', 's:7ff'])
        self.assertTrue(_wait(lambda: bus.frames()['play'] is None))
        self.assertEqual(sorted(set(sent)), [0x101, 0x102])
        self.assertEqual(bus.frames()['play_last']['skipped'], 11)
        sent.clear()
        bus.play_start('t.log', 'view', speed=0.2)
        bus.play_control('set', skip=['s:100', 's:101', 's:102'])
        self.assertEqual(bus.frames()['play']['skip'], ['s:100', 's:101', 's:102'])
        bus.play_control('stop')

    def test_api(self):
        self.write('d/t.log', TRACE)
        c = client(logged_in=True)
        info = c.get('/api/can/traces/info?path=d/t.log').get_json()
        self.assertEqual((info['frames'], info['path']), (32, 'd/t.log'))
        page = c.get('/api/can/traces/frames?path=d/t.log&start=30&limit=10').get_json()
        self.assertEqual([f['n'] for f in page['frames']], [30, 31])
        self.assertEqual(c.get('/api/can/traces/frames?path=d/t.log&start=x').status_code, 400)
        self.assertEqual(c.get('/api/can/traces/info?path=nope.log').status_code, 404)


class Api(Base):
    def test_files_api(self):
        c = client(logged_in=True)
        r = c.post('/api/can/traces', json={'action': 'mkdir', 'path': 'bench'})
        self.assertEqual(r.status_code, 200, r.get_json())
        r = c.post('/api/can/traces/upload', data={'folder': 'bench', 'file': (io.BytesIO(TRACE.encode()), 'run.log')},
                   content_type='multipart/form-data')
        self.assertEqual(r.get_json()['path'], 'bench/run.log')
        tree = c.get('/api/can/traces').get_json()['tree']
        self.assertEqual(tree[0]['children'][0]['size'], len(TRACE))
        r = c.get('/api/can/traces/download?path=bench/run.log')
        self.assertEqual(r.data.decode(), TRACE)
        r.close()
        self.assertEqual(c.get('/api/can/traces/download?path=../config.json').status_code, 400)
        r = c.post('/api/can/traces', json={'action': 'rename', 'path': 'bench/run.log', 'name': 'first'})
        self.assertEqual(r.get_json()['path'], 'bench/first.log')
        r = c.post('/api/can/traces', json={'action': 'delete', 'path': 'bench'})
        self.assertEqual(r.get_json()['tree'], [])
        self.assertEqual(c.post('/api/can/traces', json={'action': 'delete', 'path': 'bench'}).status_code, 404)


if __name__ == '__main__':
    unittest.main()


class TxList(unittest.TestCase):
    """Cyclic jobs of the TX list: tags, live update of frame and period; profiles in config."""

    def setUp(self):
        self.bus = _bus()
        self.sent = []
        self.bus._send_raw = lambda raw, dlc, payload: self.sent.append((time.monotonic(), raw, payload))

    def tearDown(self):
        self.bus.stop_cyclic()

    def test_live_update(self):
        job = self.bus.start_cyclic('123', False, False, '01 02', 20, tag='row1')
        self.assertEqual(self.bus.start_cyclic('124', False, False, 'AA', 20, tag='row1'), job)   # same tag: replaced
        self.assertTrue(_wait(lambda: len(self.sent) >= 3))
        self.assertEqual(self.sent[-1][1:], (0x124, b'\xaa'))
        self.bus.update_cyclic(job, '18FF50E5', False, False, '11 22 33', None)
        self.assertTrue(_wait(lambda: self.sent[-1][1] == 0x18FF50E5 | net.CAN_EFF_FLAG))
        self.assertEqual(self.sent[-1][2], b'\x11\x22\x33')
        j = self.bus.frames()['jobs'][0]
        self.assertEqual((j['tag'], j['data'], j['ext'], j['updated']), ('row1', '112233', True, 1))
        with self.assertRaises(net.NetError):
            self.bus.update_cyclic(job, 'zz', False, False, '', None)
        with self.assertRaises(net.NetError):
            self.bus.update_cyclic(999, '1', False, False, '', None)

    def test_period_change_applies_at_once(self):
        job = self.bus.start_cyclic('123', False, False, '', 3000, tag='slow')
        self.assertTrue(_wait(lambda: len(self.sent) == 1))
        t0 = time.monotonic()
        self.bus.update_cyclic(job, period_ms=30)          # no waiting for the rest of 3 s
        self.assertTrue(_wait(lambda: len(self.sent) >= 4, timeout=2))
        self.assertLess(time.monotonic() - t0, 1)
        self.assertEqual(self.bus.frames()['jobs'][0]['period_ms'], 30)

    def test_stop_ends_long_wait(self):
        job = self.bus.start_cyclic('123', False, False, '', 3600000)
        self.assertTrue(_wait(lambda: len(self.sent) == 1))
        self.bus.stop_cyclic(job)
        self.assertEqual(self.bus.frames()['jobs'], [])

    def test_profiles(self):
        data = net.check_profiles({'profiles': [
            {'name': 'Dash', 'note': 'n', 'tx': [{'uid': 'r1', 'name': 'rpm', 'id': '3FD', 'data': '00 01', 'period': 100, 'on': 1},
                                                 {'uid': 'r1', 'id': '1', 'period': 'x'}, 'junk']},
            {'name': 'Other'}], 'current': 'nope'})
        self.assertEqual(data['current'], 'Dash')
        rows = data['profiles'][0]['tx']
        self.assertEqual(rows[0], {'uid': 'r1', 'name': 'rpm', 'id': '3FD', 'ext': False, 'rtr': False, 'data': '00 01',
                                   'period': 100, 'on': True, 'fields': []})
        self.assertNotEqual(rows[1]['uid'], 'r1')          # duplicate uid replaced
        self.assertEqual(rows[1]['period'], 0)
        fields = net.check_profiles({'profiles': [{'name': 'F', 'tx': [{'uid': 'f', 'fields': [
            {'type': 'u16', 'byte': 9, 'order': 'be', 'scale': 0, 'offset': 'x', 'min': 0, 'max': '250', 'name': 'speed'},
            {'type': 'bit', 'byte': 2, 'bit': 7}, {'type': 'float'}, 'junk']}]}]})['profiles'][0]['tx'][0]['fields']
        self.assertEqual(fields[0], {'name': 'speed', 'type': 'u16', 'byte': 7, 'bit': 0, 'order': 'be', 'scale': 1,
                                     'offset': 0, 'step': 1, 'min': 0, 'max': 250})
        self.assertEqual([f['type'] for f in fields], ['u16', 'bit'])
        for bad in [{'profiles': 'x'}, {'profiles': [{'name': 'a'}, {'name': 'a'}]}]:
            with self.assertRaises(net.NetError):
                net.check_profiles(bad)

    def test_profiles_api(self):
        c = client(logged_in=True)
        r = c.post('/api/can/profiles', json={'profiles': [{'name': 'Dash', 'tx': [{'uid': 'a', 'id': '123'}]}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get('/api/can/profiles').get_json()['profiles'][0]['tx'][0]['id'], '123')
        self.assertTrue(os.path.isfile(os.path.join(config.profiles_dir(), 'can.json')))     # in git, not config.json
        self.assertEqual(c.post('/api/can/profiles', json={'profiles': 5}).status_code, 400)


class Watch(unittest.TestCase):
    def test_every_frame_of_one_id(self):
        bus = _bus()
        with bus._lock:
            bus._record('rx', 0x7C0, 1, b'\x00', t=1.0)          # already in the trace buffer: seeds the watch
        d = bus.watch('s:7c0')
        self.assertEqual([f['data'] for f in d['frames']], ['00'])
        with bus._lock:
            for i in range(net.CanBus.MAX_FRAMES + 100):         # the trace buffer overflows, the watch does not
                bus._record('rx', 0x3FD, 0, b'')
                if i % 10 == 0:
                    bus._record('rx', 0x7C0, 1, bytes([i % 256]))
            bus._record('rx', 0x7C0 | net.CAN_EFF_FLAG, 0, b'')  # extended 7C0 is another ID
        d2 = bus.watch('s:7c0', d['next'])
        self.assertEqual(len(d2['frames']), 210)
        self.assertEqual(len(bus.watch('s:7c0')['frames']), 211)
        self.assertEqual(bus.watch('s:3fd')['frames'][-1]['can_id'], 0x3FD)   # new key: restarted
        with self.assertRaises(can_trace.TraceError):
            bus.watch('7c0')
        bus.watch_stop()
        self.assertIsNone(bus._watch_key)


class Checksum(unittest.TestCase):
    """Toyota checksum + rolling counter, applied by the server to every transmission."""

    def test_toyota_examples(self):
        data = bytes.fromhex('00000000002710')
        self.assertEqual(net.checksum('toyota', 0x0B4, 8, data + b'\0'), 0xF3)       # 0xBC + 0x27 + 0x10
        self.assertEqual(net.checksum('sum8', 0x0B4, 8, data + b'\0'), 0x37)
        self.assertEqual(net.checksum('xor8', 0x0B4, 3, b'\x0f\xf0\x99'), 0xFF)
        raw = 0x0B4
        frames = [net.apply_mods(raw, 8, bytes.fromhex('0000000000271000'), 'toyota', (4, 0, 8), n).hex(' ').upper()
                  for n in (0, 1, 2, 13, 256)]
        self.assertEqual(frames, ['00 00 00 00 00 27 10 F3', '00 00 00 00 01 27 10 F4', '00 00 00 00 02 27 10 F5',
                                  '00 00 00 00 0D 27 10 00', '00 00 00 00 00 27 10 F3'])        # CS passes 0xFF; N wraps

    def test_counter_bits_and_extended_id(self):
        # high nibble counter of byte 1, starting from the value in the data (3), low nibble untouched
        p = net.apply_mods(0x123, 2, b'\x00\x3a', '', (1, 4, 4), 14)
        self.assertEqual(p, bytes([0x00, 0x1a]))                                    # (3 + 14) & 0xF = 1
        raw = 0x18FF50E5 | net.CAN_EFF_FLAG
        self.assertEqual(net.checksum('toyota', raw, 2, b'\x01\x00'), (0x18 + 0xFF + 0x50 + 0xE5 + 2 + 1) & 0xFF)
        self.assertEqual(net.apply_mods(0x7FF | net.CAN_RTR_FLAG, 2, b'', 'toyota', None), b'')
        with self.assertRaises(net.NetError):
            net.check_mods('crc32')
        with self.assertRaises(net.NetError):
            net.check_mods('', {'byte': 9})
        self.assertEqual(net.check_mods('toyota', {'byte': 4, 'bits': '0-3'}), ('toyota', (4, 0, 4)))

    def test_every_cyclic_frame(self):
        bus = _bus()
        sent = []
        bus._send_raw = lambda raw, dlc, payload: sent.append(payload)
        job = bus.start_cyclic('0B4', False, False, '00 00 00 00 00 27 10 00', 10, tag='spd',
                               cs='toyota', cnt={'byte': 4, 'bits': '0-7'})
        self.assertTrue(_wait(lambda: len(sent) >= 5))
        for k, p in enumerate(sent[:5]):
            self.assertEqual((p[4], p[7]), (k, (0xF3 + k) & 0xFF))
        # live edit (speed 0x2710 -> 0x2EE0): the counter keeps running, the checksum follows
        bus.update_cyclic(job, '0B4', False, False, '00 00 00 00 00 2E E0 00', None, cs='toyota', cnt={'byte': 4})
        n = len(sent)
        self.assertTrue(_wait(lambda: len(sent) >= n + 3))
        p = sent[-1]
        self.assertEqual(p[5:7], b'\x2e\xe0')
        self.assertGreaterEqual(p[4], 5)
        self.assertEqual(p[7], net.checksum('toyota', 0x0B4, 8, p))
        bus.stop_cyclic()
        sent.clear()
        bus.send('0B4', data='00 00 00 00 07 27 10 00', cs='toyota')                # single send: checksum only
        self.assertEqual(sent[0].hex(' ').upper(), '00 00 00 00 07 27 10 FA')
        j = net.check_profiles({'profiles': [{'name': 'a', 'tx': [{'uid': 'x', 'cs': 'toyota', 'cnt': {'byte': 4, 'bits': '0-3'}},
                                                                   {'uid': 'y', 'cs': 'md5', 'cnt': {'byte': 99}}]}]})
        rows = j['profiles'][0]['tx']
        self.assertEqual((rows[0]['cs'], rows[0]['cnt']), ('toyota', {'byte': 4, 'bits': '0-3'}))
        self.assertNotIn('cs', rows[1])
        self.assertNotIn('cnt', rows[1])
