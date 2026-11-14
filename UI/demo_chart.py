"""Demo: splash screen (UI/images/splash.png, else the background of the settings) and a live chart."""
import math
import random
import time

import smms_ui
smms_ui.setup()

from kivy.app import App                                   # noqa: E402  (after setup)
from kivy.clock import Clock                               # noqa: E402
from kivy.core.window import Window                        # noqa: E402
from kivy.metrics import dp, sp                            # noqa: E402
from kivy.uix.boxlayout import BoxLayout                   # noqa: E402
from kivy.uix.button import Button                         # noqa: E402
from kivy.uix.image import Image                           # noqa: E402
from kivy.uix.label import Label                           # noqa: E402
from kivy.uix.floatlayout import FloatLayout              # noqa: E402
from kivy.uix.screenmanager import FadeTransition, Screen, ScreenManager   # noqa: E402

T = smms_ui.THEME
Card, LineChart = smms_ui.widgets()
SPLASH_SECONDS = 3
HZ = 20


def lab(text='', size=16, color=None, **kw):
    kw.setdefault('halign', 'center')
    kw.setdefault('valign', 'middle')
    w = Label(text=text, font_size=sp(size), color=color or T['text'], markup=True, **kw)
    w.bind(size=lambda o, s: setattr(o, 'text_size', s))
    return w


class Splash(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = FloatLayout()
        pic = smms_ui.image('splash.png') or smms_ui.image('splash.jpg') or smms_ui.background()
        if pic:                                    # the picture fills the screen, the title on a band over it
            root.add_widget(Image(source=pic, allow_stretch=True, keep_ratio=False))
        band = Card(orientation='vertical', size_hint=(1, 0.3), pos_hint={'x': 0, 'center_y': 0.5},
                    bg=(0, 0, 0, 0.55) if pic else T['bg'])
        band.add_widget(lab('[b]SystemMngmntService[/b]', 56, T['accent']))
        band.add_widget(lab('device display' + ('' if pic else ' · a picture: UI/images/splash.png or a background'),
                            18, T['text'] if pic else T['dim'], size_hint_y=0.4))
        root.add_widget(band)
        self.add_widget(root)


class ChartScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation='vertical', padding=dp(12), spacing=dp(10))
        top = BoxLayout(size_hint_y=None, height=dp(40))
        top.add_widget(lab('[b]Demo: live chart[/b]', 22, T['accent'], halign='left'))
        self.values = lab('', 18, halign='right')
        top.add_widget(self.values)
        root.add_widget(top)
        card = Card(orientation='vertical')
        card.add_widget(lab(f'[color={smms_ui.hexcolor(T["info"])}]sine[/color]   '
                            f'[color={smms_ui.hexcolor(T["warn"])}]noise[/color]   last 30 s, 0…100',
                            14, T['dim'], size_hint_y=None, height=dp(22), halign='left'))
        self.chart = LineChart(series=[{'color': T['info']}, {'color': T['warn'], 'dash': True}], ymax=100, window=30)
        card.add_widget(self.chart)
        root.add_widget(card)
        row = BoxLayout(size_hint_y=None, height=dp(70), spacing=dp(10))
        self.pause = Button(text='Pause', font_size=sp(22), background_normal='', background_color=T['panel2'])
        clear = Button(text='Clear', font_size=sp(22), background_normal='', background_color=T['panel2'])
        self.speed = Button(text='Speed ×1', font_size=sp(22), background_normal='', background_color=T['panel2'])
        splash = Button(text='Splash', font_size=sp(22), background_normal='', background_color=T['panel2'])
        self.pause.bind(on_release=self.toggle)
        clear.bind(on_release=self.clear)
        self.speed.bind(on_release=self.faster)
        splash.bind(on_release=lambda w: App.get_running_app().show_splash())
        for w in (self.pause, clear, self.speed, splash):
            row.add_widget(w)
        root.add_widget(row)
        self.add_widget(root)
        self.k, self.phase, self.paused, self.noise = 1, 0.0, False, 50.0
        Clock.schedule_interval(self.tick, 1 / HZ)

    def toggle(self, w):
        self.paused = not self.paused
        w.text = 'Run' if self.paused else 'Pause'
        w.background_color = T['warn'] if self.paused else T['panel2']

    def clear(self, w):
        for s in self.chart.series:
            s['points'].clear()
        self.chart.redraw()

    def faster(self, w):
        self.k = self.k % 4 + 1
        w.text = f'Speed ×{self.k}'

    def tick(self, dt):
        if self.paused or self.manager.current != self.name:
            return
        t = time.time()
        self.phase += dt * self.k
        a = 50 + 40 * math.sin(self.phase)
        self.noise = max(0, min(100, self.noise + random.uniform(-6, 6)))
        self.chart.push(0, t, a, keep=HZ * 40)
        self.chart.push(1, t, self.noise, keep=HZ * 40)
        self.chart.redraw()
        self.values.text = f'[color={smms_ui.hexcolor(T["info"])}]{a:5.1f}[/color]   ' \
                           f'[color={smms_ui.hexcolor(T["warn"])}]{self.noise:5.1f}[/color]'


class DemoChartApp(App):
    title = 'Demo: chart'

    def build(self):
        Window.clearcolor = T['bg']
        self.sm = ScreenManager(transition=FadeTransition(duration=0.6))
        self.sm.add_widget(Splash(name='splash'))
        self.sm.add_widget(ChartScreen(name='chart'))
        self.show_splash()
        return self.sm

    def show_splash(self):
        self.sm.current = 'splash'
        Clock.schedule_once(lambda dt: setattr(self.sm, 'current', 'chart'), SPLASH_SECONDS)


if __name__ == '__main__':
    DemoChartApp().run()
