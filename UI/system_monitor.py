"""System monitor: CPU, memory, temperature, network, disks of this board and a running clone / image job."""
import time

import smms_ui
smms_ui.setup()

from kivy.app import App                                   # noqa: E402  (after setup)
from kivy.clock import Clock                               # noqa: E402
from kivy.metrics import dp, sp                            # noqa: E402
from kivy.uix.boxlayout import BoxLayout                   # noqa: E402
from kivy.uix.gridlayout import GridLayout                 # noqa: E402
from kivy.uix.label import Label                           # noqa: E402
from kivy.uix.progressbar import ProgressBar               # noqa: E402
from kivy.core.window import Window                        # noqa: E402

T = smms_ui.THEME
Card, LineChart = smms_ui.widgets()
WINDOW_S = 300


def level(v, warn, crit):
    return T['danger'] if v is not None and v >= crit else T['warn'] if v is not None and v >= warn else T['text']


def lab(text='', size=14, color=None, bold=False, **kw):
    kw.setdefault('halign', 'left')
    kw.setdefault('valign', 'middle')
    w = Label(text=text, font_size=sp(size), color=color or T['text'], bold=bold, markup=True, **kw)
    w.bind(size=lambda o, s: setattr(o, 'text_size', s))
    return w


class Tile(Card):
    """Label, big value, small line under it."""
    def __init__(self, title, **kw):
        super().__init__(orientation='vertical', **kw)
        self.head = lab(title.upper(), 12, T['dim'], size_hint_y=0.25)
        self.value = lab('—', 30, bold=True, size_hint_y=0.45)
        self.sub = lab('', 12, T['dim'], size_hint_y=0.3)
        for w in (self.head, self.value, self.sub):
            self.add_widget(w)


class ChartBox(Card):
    def __init__(self, title, series, ymax=0, **kw):
        super().__init__(orientation='vertical', **kw)
        self.head = lab(title, 13, T['dim'], size_hint_y=None, height=dp(22))
        self.chart = LineChart(series=series, ymax=ymax, window=WINDOW_S)
        self.add_widget(self.head)
        self.add_widget(self.chart)


class Monitor(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation='vertical', padding=dp(10), spacing=dp(8), **kw)
        Window.clearcolor = T['bg']
        # top bar: host, addresses, clock
        bar = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(12))
        self.host = lab('[b]System monitor[/b]', 20, T['accent'])
        self.addr = lab('', 14, T['info'], halign='center')
        self.clock = lab('', 20, halign='right')
        for w in (self.host, self.addr, self.clock):
            bar.add_widget(w)
        self.add_widget(bar)
        # job strip (clone / image job of HW Utils), hidden when idle
        self.job = Card(orientation='vertical', size_hint_y=None, height=0, opacity=0, bg=T['panel2'])
        self.job_text = lab('', 14, T['info'])
        self.job_bar = ProgressBar(max=100)
        self.job.add_widget(self.job_text)
        self.job.add_widget(self.job_bar)
        self.add_widget(self.job)
        # tiles
        tiles = GridLayout(cols=5, spacing=dp(8), size_hint_y=0.24)
        self.t_cpu, self.t_ram, self.t_temp, self.t_net, self.t_up = (
            Tile('CPU'), Tile('Memory'), Tile('Temperature'), Tile('Network'), Tile('Uptime'))
        for t in (self.t_cpu, self.t_ram, self.t_temp, self.t_net, self.t_up):
            tiles.add_widget(t)
        self.add_widget(tiles)
        # charts: one unit per chart (%, rate)
        charts = BoxLayout(spacing=dp(8), size_hint_y=0.46)
        self.c_load = ChartBox('CPU / RAM, %  (5 min)', [{'color': T['accent']}, {'color': T['info']}], ymax=100)
        self.c_net = ChartBox('Network, rate  (5 min)', [{'color': T['info']}, {'color': T['warn'], 'dash': True}])
        charts.add_widget(self.c_load)
        charts.add_widget(self.c_net)
        self.add_widget(charts)
        # disks
        self.disks = Card(orientation='vertical', size_hint_y=0.3, spacing=dp(4))
        self.add_widget(self.disks)
        self.status = lab('', 12, T['dim'], size_hint_y=None, height=dp(18))
        self.add_widget(self.status)
        self.last_t = 0
        self.stop_poll = smms_ui.poll(lambda: f'/api/monitor?since={self.last_t}', 2, self.update, self.failed)
        Clock.schedule_interval(lambda dt: setattr(self.clock, 'text', time.strftime('%H:%M:%S')), 1)

    def failed(self, msg):
        self.status.text = f'[color={smms_ui.hexcolor(T["danger"])}]{msg}[/color]'

    def update(self, d):
        self.status.text = f'updated {time.strftime("%H:%M:%S")}'
        for row in d.get('history', []):
            t, cpu, mem, rx, tx = row[0], row[1], row[2], row[3], row[4]
            self.c_load.chart.push(0, t, cpu or 0)
            self.c_load.chart.push(1, t, mem or 0)
            self.c_net.chart.push(0, t, rx or 0)
            self.c_net.chart.push(1, t, tx or 0)
            self.last_t = t
        self.c_load.chart.redraw()
        self.c_net.chart.redraw()
        c = d.get('current') or {}
        cpu, mem, net = c.get('cpu') or {}, c.get('mem') or {}, c.get('net') or {}
        self.host.text = f'[b]{d.get("hostname", "")}[/b]  [color={smms_ui.hexcolor(T["dim"])}]system monitor[/color]'
        self.addr.text = '  '.join(a.split('/')[0] for a in net.get('addrs', []) if ':' not in a)
        if cpu:
            self.t_cpu.value.text, self.t_cpu.value.color = f'{cpu["pct"]:.0f} %', level(cpu['pct'], 70, 90)
            self.t_cpu.sub.text = f'{cpu["count"]} cores · {cpu.get("freq_mhz") or "?"} MHz · load {" ".join(cpu["load"])}'
        if mem:
            self.t_ram.value.text, self.t_ram.value.color = f'{mem["pct"]:.0f} %', level(mem['pct'], 80, 92)
            self.t_ram.sub.text = f'{smms_ui.fmt_bytes(mem["used"])} / {smms_ui.fmt_bytes(mem["total"])}'
        temp = c.get('temp')
        self.t_temp.value.text = f'{temp:.1f} °C' if temp is not None else '—'
        self.t_temp.value.color = level(temp, 70, 85)
        self.t_temp.sub.text = ' · '.join(f'{s["name"]} {s["temp"]}°' for s in c.get('sensors', [])[:2])
        self.t_net.value.text = f'RX {smms_ui.fmt_rate(net.get("rx_rate"))}'
        self.t_net.sub.text = f'TX {smms_ui.fmt_rate(net.get("tx_rate"))} · {net.get("iface") or "no link"}'
        self.t_net.value.font_size = sp(22)
        self.t_up.value.text = smms_ui.fmt_uptime(d.get('uptime'))
        self.t_up.sub.text = f'{c.get("procs", "?")} processes'
        self.c_net.head.text = (f'Network  [color={smms_ui.hexcolor(T["info"])}]RX {smms_ui.fmt_rate(net.get("rx_rate"))}[/color]'
                                f'   [color={smms_ui.hexcolor(T["warn"])}]TX {smms_ui.fmt_rate(net.get("tx_rate"))}[/color]')
        self.c_load.head.text = (f'[color={smms_ui.hexcolor(T["accent"])}]CPU {cpu.get("pct", 0):.0f} %[/color]   '
                                 f'[color={smms_ui.hexcolor(T["info"])}]RAM {mem.get("pct", 0):.0f} %[/color]   5 min')
        self._disks(d.get('blocks', []), c.get('disk') or {})
        self._job(d.get('job'))

    def _disks(self, blocks, io):
        self.disks.clear_widgets()
        self.disks.add_widget(lab('DISKS', 12, T['dim'], size_hint_y=None, height=dp(18)))
        rows = []
        for b in blocks:
            for x in [b] + b.get('children', []):
                if x.get('fssize'):
                    rows.append(x)
        for x in rows[:4]:
            pct = x['fsused'] * 100 / x['fssize']
            s = io.get(x['name']) or {}
            row = BoxLayout(spacing=dp(8))
            row.add_widget(lab(f'[b]{x["name"]}[/b]  {", ".join(x.get("mounts", [])[:2])}', 13, size_hint_x=0.38))
            bar = ProgressBar(max=100, value=pct, size_hint_x=0.3)
            row.add_widget(bar)
            row.add_widget(lab(f'{smms_ui.fmt_bytes(x["fsused"])} / {smms_ui.fmt_bytes(x["fssize"])}  {pct:.0f} %', 12,
                               level(pct, 80, 92), size_hint_x=0.2))
            row.add_widget(lab(f'R {smms_ui.fmt_rate(s.get("read_rate"))}  W {smms_ui.fmt_rate(s.get("write_rate"))}',
                               11, T['dim'], size_hint_x=0.12))
            self.disks.add_widget(row)
        if not rows:
            self.disks.add_widget(lab('no mounted file systems', 13, T['dim']))

    def _job(self, j):
        if not j:
            self.job.height, self.job.opacity = 0, 0
            return
        self.job.height, self.job.opacity = dp(58), 1
        p = j.get('progress') or {}
        self.job_bar.value = p.get('percent', 0)
        m, s = divmod(int(j.get('elapsed', 0)), 60)
        stall = ' — NO OUTPUT, stuck in the kernel?' if j.get('stall') else ''
        self.job_text.text = (f'[b]{j["title"]}[/b]  {j["state"]}  {m}:{s:02d}  '
                              + (f'{p["percent"]} % · {p.get("speed", "")} · ETA {p.get("eta", "")}' if p else 'preparing…')
                              + stall)
        self.job_text.color = T['warn'] if stall else T['info']


class SystemMonitorApp(App):
    title = 'System monitor'

    def build(self):
        return Monitor()

    def on_stop(self):
        if self.root:
            self.root.stop_poll()


if __name__ == '__main__':
    SystemMonitorApp().run()
