"""Test platform: start / stop a test, its steps and verdict; operator prompts answered on the touch screen."""
import time

import smms_ui
smms_ui.setup(keyboard=True)

from kivy.app import App                                   # noqa: E402  (after setup)
from kivy.clock import Clock                               # noqa: E402
from kivy.core.window import Window                        # noqa: E402
from kivy.metrics import dp, sp                            # noqa: E402
from kivy.uix.boxlayout import BoxLayout                   # noqa: E402
from kivy.uix.button import Button                         # noqa: E402
from kivy.uix.gridlayout import GridLayout                 # noqa: E402
from kivy.uix.label import Label                           # noqa: E402
from kivy.uix.modalview import ModalView                   # noqa: E402
from kivy.uix.scrollview import ScrollView                 # noqa: E402
from kivy.uix.spinner import Spinner                       # noqa: E402
from kivy.uix.textinput import TextInput                   # noqa: E402

T = smms_ui.THEME
Card, _ = smms_ui.widgets()
STATE_COLOR = {'RUNNING': T['info'], 'PASS': T['ok'], 'FAIL': T['danger'], 'ERROR': T['warn'], 'STOPPED': T['dim']}
ROW_COLOR = {'PASS': T['ok'], 'FAIL': T['danger'], 'ERROR': T['warn'], 'INFO': T['info'], 'SECTION': T['dim']}
MAX_ROWS = 300


def lab(text='', size=15, color=None, bold=False, **kw):
    kw.setdefault('halign', 'left')
    kw.setdefault('valign', 'middle')
    w = Label(text=text, font_size=sp(size), color=color or T['text'], bold=bold, markup=True, **kw)
    w.bind(size=lambda o, s: setattr(o, 'text_size', s))
    return w


def btn(text, color, **kw):
    return Button(text=text, font_size=sp(20), bold=True, background_normal='', background_color=color, **kw)


class Prompt(ModalView):
    """Operator question of the running script (TestStrategy.ask*): buttons / choice / number keypad / text."""
    def __init__(self, run_id, p, on_done, **kw):
        super().__init__(size_hint=(0.8, 0.75), auto_dismiss=False, background_color=(0, 0, 0, 0.7), **kw)
        self.run_id, self.p, self.on_done = run_id, p, on_done
        box = Card(orientation='vertical', spacing=dp(10), padding=dp(16))
        box.add_widget(lab(f'[b]{p.get("name") or "Operator"}[/b]', 22, T['accent'], size_hint_y=None, height=dp(36)))
        box.add_widget(lab(p.get('message', ''), 20, halign='center'))
        self.err = lab('', 14, T['danger'], halign='center', size_hint_y=None, height=dp(22))
        kind = p['type']
        if kind in ('buttons', 'choice'):
            opts = p.get('options') or ['OK']
            grid = GridLayout(cols=min(len(opts), 3), spacing=dp(10), size_hint_y=None,
                              height=dp(80) * ((len(opts) + 2) // 3))
            for o in opts:
                color = T['ok'] if o.lower() in ('yes', 'ok', 'pass', 'так') else \
                    T['danger'] if o.lower() in ('no', 'fail', 'ні') else T['panel2']
                b = btn(o, color)
                b.bind(on_release=lambda w, o=o: self.send(o))
                grid.add_widget(b)
            box.add_widget(grid)
        else:
            row = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(10))
            self.inp = TextInput(text=str(p.get('default') if p.get('default') is not None else ''), multiline=False,
                                 font_size=sp(26), input_filter='float' if kind == 'number' else None)
            row.add_widget(self.inp)
            if p.get('units'):
                row.add_widget(lab(p['units'], 22, size_hint_x=0.15))
            box.add_widget(row)
            if kind == 'number':
                pad = GridLayout(cols=5, spacing=dp(6), size_hint_y=None, height=dp(170))
                for k in ['7', '8', '9', '-', '⌫', 'C', '4', '5', '6', '.', '0', '00', '1', '2', '3']:
                    b = btn(k, T['panel2'])
                    b.bind(on_release=lambda w, k=k: self.key(k))
                    pad.add_widget(b)
                box.add_widget(pad)
            ok = btn('OK', T['ok'], size_hint_y=None, height=dp(64))
            ok.bind(on_release=lambda w: self.send(self.inp.text))
            box.add_widget(ok)
        box.add_widget(self.err)
        self.add_widget(box)

    def key(self, k):
        t = self.inp.text
        self.inp.text = '' if k == 'C' else t[:-1] if k == '⌫' else t + k

    def send(self, value):
        body = {'run_id': self.run_id, 'prompt_id': self.p['id'], 'value': value}
        smms_ui.in_background(lambda: smms_ui.api.post('/api/tests/answer', body),
                              lambda r: (self.dismiss(), self.on_done()),
                              lambda m: setattr(self.err, 'text', m))


class Confirm(ModalView):
    def __init__(self, text, action, **kw):
        super().__init__(size_hint=(0.6, 0.4), background_color=(0, 0, 0, 0.7), **kw)
        box = Card(orientation='vertical', padding=dp(16), spacing=dp(12))
        box.add_widget(lab(text, 22, halign='center'))
        row = BoxLayout(spacing=dp(12), size_hint_y=None, height=dp(70))
        yes, no = btn('Yes', T['danger']), btn('No', T['panel2'])
        yes.bind(on_release=lambda w: (self.dismiss(), action()))
        no.bind(on_release=lambda w: self.dismiss())
        row.add_widget(yes)
        row.add_widget(no)
        box.add_widget(row)
        self.add_widget(box)


class TestScreen(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation='vertical', padding=dp(10), spacing=dp(8), **kw)
        Window.clearcolor = T['bg']
        self.run_id, self.got, self.prompt_id, self.modal = None, 0, None, None
        # header: script, serial, state, elapsed
        head = Card(size_hint_y=None, height=dp(90), spacing=dp(14))
        left = BoxLayout(orientation='vertical')
        self.title = lab('[b]Test platform[/b]', 24, T['accent'])
        self.sub = lab('', 15, T['dim'])
        left.add_widget(self.title)
        left.add_widget(self.sub)
        head.add_widget(left)
        self.state = lab('', 40, bold=True, halign='center', size_hint_x=0.32)
        head.add_widget(self.state)
        self.add_widget(head)
        # counts
        self.counts = lab('', 18, size_hint_y=None, height=dp(30))
        self.add_widget(self.counts)
        # results
        self.rows = GridLayout(cols=1, spacing=dp(2), size_hint_y=None)
        self.rows.bind(minimum_height=self.rows.setter('height'))
        self.scroll = ScrollView(bar_width=dp(6))
        self.scroll.add_widget(self.rows)
        card = Card()
        card.add_widget(self.scroll)
        self.add_widget(card)
        # controls
        ctl = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(10))
        self.pick = Spinner(text='choose a test', values=[], font_size=sp(18), size_hint_x=0.5,
                            background_normal='', background_color=T['panel2'])
        self.start = btn('START', T['ok'], size_hint_x=0.25)
        self.stop = btn('STOP', T['danger'], size_hint_x=0.25)
        self.start.bind(on_release=lambda w: self.do_start())
        self.stop.bind(on_release=lambda w: Confirm('Stop the running test?', self.do_stop).open())
        for w in (self.pick, self.start, self.stop):
            ctl.add_widget(w)
        self.add_widget(ctl)
        self.msg = lab('', 13, T['dim'], size_hint_y=None, height=dp(20))
        self.add_widget(self.msg)
        self.stop_poll = smms_ui.poll(self.url, 1, self.update, self.failed)
        smms_ui.in_background(lambda: smms_ui.api.get('/api/tests/scripts'), self.scripts, self.failed)
        self.render(None)

    def url(self):
        return f'/api/tests/status?run_id={self.run_id or ""}&results_from={self.got}&output_from=999999999'

    def failed(self, m):
        self.msg.text = f'[color={smms_ui.hexcolor(T["danger"])}]{m}[/color]'

    def scripts(self, d):
        names = [s['name'] for s in d.get('scripts', [])]
        self.pick.values = names
        if names and self.pick.text not in names:
            self.pick.text = names[0]

    def update(self, d):
        self.msg.text = f'updated {time.strftime("%H:%M:%S")}'
        run = d.get('run')
        if run and run['id'] != self.run_id:                 # a new run: start the list again
            self.run_id, self.got = run['id'], 0
            self.rows.clear_widgets()
        if run:
            for r in run.get('results', []):
                self.add_row(r)
            self.got += len(run.get('results', []))
        self.render(run)

    def add_row(self, r):
        st = r.get('status', '')
        if st == 'SECTION':
            w = lab(f'[b]{r.get("name", "")}[/b]', 16, T['accent'], size_hint_y=None, height=dp(30))
        else:
            row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
            row.add_widget(lab(r.get('name', ''), 15, size_hint_x=0.5))
            row.add_widget(lab(f'{r.get("condition", "")} {r.get("units", "")}', 15, T['dim'], size_hint_x=0.35))
            row.add_widget(lab(f'[b]{st}[/b]', 15, ROW_COLOR.get(st, T['text']), halign='right', size_hint_x=0.15))
            w = row
        self.rows.add_widget(w)
        while len(self.rows.children) > MAX_ROWS:
            self.rows.remove_widget(self.rows.children[-1])
        Clock.schedule_once(self._follow, 0)

    def _follow(self, dt):
        """Keep the newest row in view; while the list is shorter than the view it stays at the top (scroll_y = 0
        would sit it at the bottom and make it jump with every new row)."""
        self.scroll.scroll_y = 0 if self.rows.height > self.scroll.height else 1

    def render(self, run):
        running = bool(run and run['state'] == 'RUNNING')
        self.start.disabled = running or not self.pick.values
        self.stop.disabled = not running
        self.pick.disabled = running
        if not run:
            self.title.text, self.sub.text = '[b]Test platform[/b]', 'no test has run since the panel started'
            self.state.text, self.counts.text = 'READY', ''
            self.state.color = T['dim']
            return
        m, s = divmod(int(run.get('elapsed') or 0), 60)
        self.title.text = f'[b]{run["script"]}[/b]'
        self.sub.text = (f'S/N {run["serial"]}   ' if run.get('serial') else '') + f'{m}:{s:02d}' + \
            ('   stop on fail' if run.get('stop_on_fail') else '')
        self.state.text, self.state.color = run['state'], STATE_COLOR.get(run['state'], T['text'])
        c = run.get('counts') or {}
        self.counts.text = '   '.join(f'[color={smms_ui.hexcolor(ROW_COLOR[k])}]{k} {c.get(k, 0)}[/color]'
                                      for k in ('PASS', 'FAIL', 'ERROR'))
        p = run.get('prompt')
        if p and p['id'] != self.prompt_id:
            self.prompt_id = p['id']
            self.modal = Prompt(run['id'], p, lambda: None)
            self.modal.open()
        elif not p and self.modal:
            self.modal.dismiss()
            self.modal, self.prompt_id = None, None

    def do_start(self):
        smms_ui.in_background(lambda: smms_ui.api.post('/api/tests/start', {'script': self.pick.text}),
                              lambda r: setattr(self.msg, 'text', 'started'), self.failed)

    def do_stop(self):
        smms_ui.in_background(lambda: smms_ui.api.post('/api/tests/stop'),
                              lambda r: setattr(self.msg, 'text', 'stopping…'), self.failed)


class TestStatusApp(App):
    title = 'Test platform'

    def build(self):
        return TestScreen()

    def on_stop(self):
        if self.root:
            self.root.stop_poll()


if __name__ == '__main__':
    TestStatusApp().run()
