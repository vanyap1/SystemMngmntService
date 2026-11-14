"""Demo: buttons, toggle, slider and a touch area — checks the screen, the touch panel and the mouse."""
import time

import smms_ui
smms_ui.setup()

from kivy.app import App                                   # noqa: E402  (after setup)
from kivy.animation import Animation                       # noqa: E402
from kivy.clock import Clock                               # noqa: E402
from kivy.core.window import Window                        # noqa: E402
from kivy.graphics import Color, Ellipse, Line             # noqa: E402
from kivy.metrics import dp, sp                            # noqa: E402
from kivy.uix.boxlayout import BoxLayout                   # noqa: E402
from kivy.uix.button import Button                         # noqa: E402
from kivy.uix.behaviors import ButtonBehavior              # noqa: E402
from kivy.uix.image import Image                           # noqa: E402
from kivy.uix.label import Label                           # noqa: E402
from kivy.uix.progressbar import ProgressBar               # noqa: E402
from kivy.uix.slider import Slider                         # noqa: E402
from kivy.uix.togglebutton import ToggleButton             # noqa: E402
from kivy.uix.widget import Widget                         # noqa: E402

T = smms_ui.THEME
Card, _ = smms_ui.widgets()
COLORS = [T['accent'], T['info'], T['warn'], T['danger']]


def lab(text='', size=16, color=None, **kw):
    kw.setdefault('halign', 'center')
    kw.setdefault('valign', 'middle')
    w = Label(text=text, font_size=sp(size), color=color or T['text'], markup=True, **kw)
    w.bind(size=lambda o, s: setattr(o, 'text_size', s))
    return w


ICONS = [('information-icon-6057.png', 'Info'), ('network-icon-1911.png', 'Network'),
         ('services-icon-png-2295.png', 'Services'), ('exit-icon-4611.png', 'Exit')]   # from UI/images/


class IconButton(ButtonBehavior, BoxLayout):
    """A picture from UI/images/ with a caption; dims while pressed."""
    def __init__(self, path, text, **kw):
        super().__init__(orientation='vertical', padding=dp(4), **kw)
        self.add_widget(Image(source=path, allow_stretch=True, keep_ratio=True))
        self.add_widget(lab(text, 13, T['dim'], size_hint_y=0.3))

    def on_state(self, w, state):
        self.opacity = 0.5 if state == 'down' else 1


class TouchArea(Widget):
    """Draws every touch / click: a dot where it starts, a trace while it moves (each finger its own colour)."""
    def __init__(self, report, **kw):
        super().__init__(**kw)
        self.report = report
        self.n = 0
        self.hint = lab('touch or click here — several fingers at once on a multi-touch panel', 16, T['dim'])
        self.add_widget(self.hint)
        self.bind(pos=self._place, size=self._place)

    def _place(self, *_):
        self.hint.pos, self.hint.size = self.pos, self.size

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self.n += 1
        c = COLORS[self.n % len(COLORS)]
        with self.canvas:
            Color(*c)
            d = dp(28)
            Ellipse(pos=(touch.x - d / 2, touch.y - d / 2), size=(d, d))
            touch.ud['line'] = Line(points=[touch.x, touch.y], width=dp(2))
        touch.grab(self)
        self.report(touch, 'down')
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is self and 'line' in touch.ud:
            touch.ud['line'].points += [touch.x, touch.y]
            self.report(touch, 'move')
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self.report(touch, 'up')
            return True
        return super().on_touch_up(touch)

    def clear(self):
        self.canvas.clear()
        self.n = 0


class Demo(BoxLayout):
    def __init__(self, **kw):
        super().__init__(orientation='vertical', padding=dp(12), spacing=dp(10), **kw)
        Window.clearcolor = T['bg']
        s = smms_ui.settings()
        top = BoxLayout(size_hint_y=None, height=dp(40))
        top.add_widget(lab('[b]Demo: controls[/b]', 22, T['accent'], halign='left'))
        self.info = lab('', 14, T['dim'])
        top.add_widget(self.info)
        self.clock = lab('', 22, halign='right')
        top.add_widget(self.clock)
        self.add_widget(top)
        self.info.text = (f'{Window.size[0]}×{Window.size[1]} · rotation {s.get("rotation", 0)}° · '
                          f'{s.get("mode", "?")} · mouse {"yes" if smms_ui.has_mouse() else "no"}')

        body = BoxLayout(spacing=dp(12))
        left = Card(orientation='vertical', size_hint_x=0.4, spacing=dp(12))
        self.count = 0
        self.counter = lab('0', 64, T['text'], size_hint_y=0.3)
        left.add_widget(self.counter)
        row = BoxLayout(spacing=dp(10), size_hint_y=0.22)
        plus = Button(text='+1', font_size=sp(30), background_normal='', background_color=T['accent'])
        reset = Button(text='Reset', font_size=sp(24), background_normal='', background_color=T['panel2'])
        plus.bind(on_release=lambda w: self.bump(1))
        reset.bind(on_release=lambda w: self.bump(-self.count))
        row.add_widget(plus)
        row.add_widget(reset)
        left.add_widget(row)
        self.toggle = ToggleButton(text='Alarm OFF', font_size=sp(24), size_hint_y=0.2,
                                   background_normal='', background_color=T['panel2'])
        self.toggle.bind(state=self.on_toggle)
        left.add_widget(self.toggle)
        left.add_widget(lab('Level', 16, T['dim'], size_hint_y=0.08))
        self.slider = Slider(min=0, max=100, value=40, size_hint_y=0.12, cursor_size=(dp(40), dp(40)))
        self.bar = ProgressBar(max=100, value=40, size_hint_y=0.06)
        self.level = lab('40 %', 20, size_hint_y=0.1)
        self.slider.bind(value=self.on_slide)
        for w in (self.slider, self.bar, self.level):
            left.add_widget(w)
        body.add_widget(left)

        icons = [(smms_ui.image(f), t) for f, t in ICONS if smms_ui.image(f)]
        if icons:                                       # image buttons: pictures dropped into UI/images/
            row = BoxLayout(spacing=dp(10), size_hint_y=0.16)
            for path, text in icons:
                b = IconButton(path, text)
                b.bind(on_release=lambda w, text=text: setattr(self.event, 'text', f'icon button: {text}'))
                row.add_widget(b)
            left.add_widget(row)
        right = Card(orientation='vertical')
        self.area = TouchArea(self.report)
        right.add_widget(self.area)
        bottom = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(10))
        self.event = lab('', 14, T['info'], halign='left')
        clear = Button(text='Clear', size_hint_x=0.2, font_size=sp(18), background_normal='',
                       background_color=T['panel2'])
        clear.bind(on_release=lambda w: self.area.clear())
        bottom.add_widget(self.event)
        bottom.add_widget(clear)
        right.add_widget(bottom)
        body.add_widget(right)
        self.add_widget(body)
        Clock.schedule_interval(lambda dt: setattr(self.clock, 'text', time.strftime('%H:%M:%S')), 1)

    def bump(self, n):
        self.count += n
        self.counter.text = str(self.count)
        self.counter.font_size = sp(80)
        Animation(font_size=sp(64), d=0.25, t='out_quad').start(self.counter)

    def on_toggle(self, w, state):
        on = state == 'down'
        w.text = 'Alarm ON' if on else 'Alarm OFF'
        w.background_color = T['danger'] if on else T['panel2']
        Window.clearcolor = (0.18, 0.05, 0.05, 1) if on else T['bg']

    def on_slide(self, w, v):
        self.bar.value = v
        self.level.text = f'{v:.0f} %'
        self.level.color = T['danger'] if v > 80 else T['warn'] if v > 60 else T['text']

    def report(self, touch, what):
        self.event.text = f'{what}  {touch.device}  x {touch.x:.0f}  y {touch.y:.0f}' + \
            (f'  [{", ".join(sorted(touch.profile))}]' if what == 'down' else '')


class DemoControlsApp(App):
    title = 'Demo: controls'

    def build(self):
        return Demo()


if __name__ == '__main__':
    DemoControlsApp().run()
