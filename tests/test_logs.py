"""core.test_logs + /api/logs: parsing testLogs files, filters, statistics, step analysis, CSV."""
import os
import unittest

from tests.support import TMP, client, config
from core import test_logs

HEAD = ('Script:   demo_x_test.py\nSerial:   {serial}\nStop on fail: yes\nHost:     box\n'
        'Started:  2026-01-0{day} 10:00:00\n' + '-' * 100 + '\n')
FOOT = '-' * 100 + '\nFinished: 2026-01-0{day} 10:00:02  (2.0 s, exit code 0)\nResults:  x\nVERDICT:  {verdict}\n'


def step(t, status, name, cond, units=''):
    return f"[{t:8.2f}s] {status:<6} {name[:40]:<40} {cond:<28} {units}".rstrip() + '\n'


LOGS = {
    '20260101_100000_demo_x_test__SN1_FAIL.log': ('SN1', 1, 'FAIL',
        step(0.1, 'PASS', 'Power on', 'OK') + step(0.5, 'FAIL', 'Supply 5V', '4.85 < 5.61 < 5.15', 'V') +
        "             ---- Stop on fail: 'Supply 5V' failed, remaining steps skipped ----\n"
        '             ---- Finalization ----\n' + step(0.6, 'PASS', 'Power off', 'OK')),
    '20260102_100000_demo_x_test__SN1_PASS.log': ('SN1', 2, 'PASS',
        step(0.1, 'PASS', 'Power on', 'OK') + step(0.5, 'PASS', 'Supply 5V', '4.85 < 5.01 < 5.15', 'V') +
        '             | some output\n             ? operator prompt [text]: Serial?\n'
        '             > operator answer: SN1\n' + step(0.7, 'ERROR', 'A very long step name that is cut at fort',
                                                        'exit code 1: ConnectionError: cannot open DMM')),
    '20260103_100000_demo_x_test__SN2_PASS.log': ('SN2', 3, 'PASS',
        step(0.1, 'PASS', 'Power on', 'OK') + step(0.5, 'PASS', 'Supply 5V', '4.85 < 4.99 < 5.15', 'V')),
}


class TestLogs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.join(TMP, 'viewer_logs')
        os.makedirs(cls.dir, exist_ok=True)
        for name, (serial, day, verdict, body) in LOGS.items():
            with open(os.path.join(cls.dir, name), 'w') as f:
                f.write(HEAD.format(serial=serial, day=day) + body + FOOT.format(day=day, verdict=verdict))
        cls._saved = config.CFG['test_logs_dir']
        config.CFG['test_logs_dir'] = cls.dir

    @classmethod
    def tearDownClass(cls):
        config.CFG['test_logs_dir'] = cls._saved

    def test_parse(self):
        log = test_logs.parse('20260101_100000_demo_x_test__SN1_FAIL.log')
        self.assertEqual(log['header']['serial'], 'SN1')
        self.assertEqual(log['footer'], {'finished': '2026-01-01 10:00:02', 'duration': 2.0, 'exit_code': '0',
                                         'verdict': 'FAIL'})
        steps = [i for i in log['items'] if i['type'] == 'step']
        self.assertEqual(steps[1], {'type': 'step', 't': 0.5, 'status': 'FAIL', 'name': 'Supply 5V',
                                    'condition': '4.85 < 5.61 < 5.15', 'units': 'V'})
        self.assertEqual([i['name'] for i in log['items'] if i['type'] == 'section'][1], 'Finalization')
        self.assertEqual(log['first_fail']['name'], 'Supply 5V')
        self.assertEqual(log['counts'], {'PASS': 2, 'FAIL': 1, 'ERROR': 0, 'INFO': 0})

    def test_parse_output_prompts_and_long_condition(self):
        items = test_logs.parse('20260102_100000_demo_x_test__SN1_PASS.log')['items']
        types = [i['type'] for i in items]
        self.assertIn('output', types)
        self.assertEqual([i['text'] for i in items if i['type'] in ('prompt', 'answer')], ['Serial?', 'SN1'])
        err = items[-1]
        self.assertEqual(err['condition'], 'exit code 1: ConnectionError: cannot open DMM')
        self.assertEqual(err['units'], '')

    def test_invalid_names(self):
        for name in ['../config.json', 'x.log', '']:
            self.assertIsNone(test_logs.parse(name))

    def test_query_and_summary(self):
        self.assertEqual(len(test_logs.query()), 3)
        self.assertEqual(len(test_logs.query(verdict='PASS')), 2)
        self.assertEqual(len(test_logs.query(q='sn2')), 1)
        self.assertEqual(len(test_logs.query(date_from='2026-01-02', date_to='2026-01-02')), 1)
        self.assertEqual(len(test_logs.query(step='Supply 5V')), 1)
        s = test_logs.summary(test_logs.query())
        self.assertEqual(s['verdicts'], {'PASS': 2, 'FAIL': 1, 'ERROR': 0, 'STOPPED': 0})
        self.assertEqual((s['yield'], s['boards'], s['fpy']), (66.7, 2, 50.0))     # SN1 failed first
        self.assertIn({'name': 'Supply 5V', 'count': 1}, s['top_failures'])

    def test_step_values(self):
        d = test_logs.step_values(test_logs.query(), 'Supply 5V')
        st = d['stats']
        self.assertEqual((st['n'], st['lo'], st['hi'], st['min'], st['max'], st['units']), (3, 4.85, 5.15, 4.99, 5.61, 'V'))
        self.assertIn('cpk', st)

    def test_api(self):
        c = client(logged_in=True)
        d = c.get('/api/logs?verdict=PASS,FAIL&limit=2').get_json()
        self.assertEqual((d['total'], len(d['items'])), (3, 2))
        self.assertIn('demo_x_test.py', d['scripts'])
        self.assertEqual(c.get('/api/logs/view/nope_test_PASS.log').status_code, 404)
        self.assertEqual(c.get('/api/logs/step').status_code, 400)
        self.assertEqual(c.get('/api/logs?offset=x').status_code, 400)
        csv = c.get('/api/logs/export.csv?q=SN1')
        self.assertEqual(csv.status_code, 200)
        self.assertEqual(len(csv.get_data(as_text=True).strip().split('\n')), 3)       # header + 2 runs


if __name__ == '__main__':
    unittest.main()
