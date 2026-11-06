# emmcWriter on DS_H618_Core: Arduino-style pinout + block diagram -> emmcWriter_pinout.svg
# Function names follow the Python service (gpiod line names); schematic net shown in grey when different.

MONO = "Consolas, 'DejaVu Sans Mono', monospace"
SANS = "'Segoe UI', Arial, sans-serif"

INK = "#1f2937"
MUTED = "#6b7280"
FAINT = "#9ca3af"

# tag styles: (fill, stroke, text, dash)
STY = {
    "out":  ("#1f2937", "#1f2937", "#ffffff", ""),
    "in":   ("#ffffff", "#1f2937", "#1f2937", ""),
    "bus":  ("#e7e5e4", "#a8a29e", "#292524", ""),
    "pwr":  ("#f6eeee", "#b08a8a", "#7a2e2e", ""),
    "pwm":  ("#fbf6ee", "#a16a2a", "#7c4a12", "5 3"),
    "nc":   ("#6b7280", "#6b7280", "#ffffff", ""),  # in schematic, not driven by code
}
DIR = {"out": "OUT", "in": "IN", "pwm": "PWM", "nc": "—"}

# (pin, port, function, kind, badge, note)
# kind: out/in/bus/pwr/pwm/nc/free ; badge overrides direction text ; note = schematic net or alt functions
LEFT = [
    (51, "PI7", "RT_SW_B3", "in", "", "encoder 8"),
    (52, "PI8", "RT_SW_B2", "in", "", "encoder 4"),
    (53, "PI9", "RT_SW_B1", "in", "", "encoder 2"),
    (54, "PI10", "RT_SW_B0", "in", "", "encoder 1"),
    (55, "PI11", "PWM_RED", "pwm", "", "PWM1 · backlight red"),
    (56, "PI12", "PWM_GREEN", "pwm", "", "PWM2 · backlight green"),
    (57, "PI13", "", "free", "", "PWM3 · UART4_TX"),
    (58, "PI14", "", "free", "", "PWM4 · UART4_RX"),
    (59, "PI15", "USB_BR_EN", "out", "", "U36 EN · bridge power"),
    (60, "PI16", "USB_BR_OCP", "in", "", "net USB_BR_FB · U36 OC#"),
    (61, "PF6", "SYS_DET", "bus", "SDC0", "system eMMC U14"),
    (62, "PF0", "SYS_D1", "bus", "SDC0", ""),
    (63, "PF1", "SYS_D0", "bus", "SDC0", ""),
    (64, "PF2", "SYS_CLK", "bus", "SDC0", ""),
    (65, "PF3", "SYS_CMD", "bus", "SDC0", ""),
    (66, "PF4", "SYS_D3", "bus", "SDC0", ""),
    (67, "PF5", "SYS_D2", "bus", "SDC0", ""),
    (68, "GND", "GND", "pwr", "", ""),
    (69, "3V3-OUT", "3V3_OUT", "pwr", "", "encoder, pull-ups"),
    (70, "GND", "GND", "pwr", "", ""),
    (71, "1V8-OUT", "", "free", "", "1V8 out"),
    (72, "GND", "GND", "pwr", "", ""),
]
RIGHT = [
    (22, "PG14", "EMMC_BR_DET_EN", "out", "", "net CD → Q1 → SD_CD"),
    (21, "PG11", "MUX_SEL", "out", "", "net MUX_CH · 0 USB / 1 SoC"),
    (20, "PG12", "EMMC_DET", "in", "", "target socket U1"),
    (19, "PG13", "JIG_DET", "in", "", "net SW_DET · opto U31"),
    (18, "PH10", "EMMC_OCP", "in", "", "net MMC_OC · U34 OC#"),
    (17, "PH9", "EMMC_VTG", "out", "", "net MMC_VTG · U34 EN"),
    (16, "PH8", "HB_LED", "nc", "", "not in code · active-low"),
    (15, "PH7", "KP_LED", "nc", "", "not in code · active-low"),
    (14, "PH6", "LED_R", "out", "", "net R_LED"),
    (13, "PH5", "LED_Y", "out", "", "net Y_LED"),
    (12, "PH4", "LED_G", "out", "", "net G_LED"),
    (11, "PH3", "LNK_ETH", "bus", "ETH", "EPHY link LED"),
    (10, "PH2", "SPD_ETH", "bus", "ETH", "EPHY speed LED"),
    (9, "PH1", "DEB_RX", "bus", "UART0", "header H7"),
    (8, "PH0", "DEB_TX", "bus", "UART0", "header H7"),
    (7, "FEL", "FEL", "bus", "BOOT", "button SW2"),
    (6, "EPHY_TXP", "TXP_ETH", "bus", "ETH", ""),
    (5, "EPHY_TXN", "TXN_ETH", "bus", "ETH", ""),
    (4, "EPHY_RXP", "RXP_ETH", "bus", "ETH", ""),
    (3, "EPHY_RXN", "RXN_ETH", "bus", "ETH", ""),
    (2, "HTX2P", "", "free", "", "HDMI"),
    (1, "HTX2N", "", "free", "", "HDMI"),
]
TOP = [
    (50, "PI6", "", "free", "", "UART2_RX · TWI0_SDA"),
    (49, "PI5", "", "free", "", "UART2_TX · TWI0_SCK"),
    (48, "PI4", "", "free", "", "I2S0_DIN0"),
    (47, "PI3", "", "free", "", "I2S0_DOUT0"),
    (46, "PI2", "", "free", "", "I2S0_LRCK"),
    (45, "PI1", "", "free", "", "I2S0_BCLK"),
    (44, "PI0", "", "free", "", "I2S0_MCLK"),
    (43, "PG17", "", "free", "", "UART2_RTS"),
    (42, "PG19", "", "free", "", "PWM1 (=PI11)"),
    (41, "PG18", "", "free", "", "UART2_CTS"),
    (40, "PG16", "", "free", "", "UART2_RX · TWI4_SDA"),
    (39, "PG15", "", "free", "", "UART2_TX · TWI4_SCK"),
    (38, "PG10", "", "free", "", "I2S2_MCLK"),
    (37, "PG8", "", "free", "", "UART1_RTS"),
    (36, "PG9", "", "free", "", "UART1_CTS"),
    (35, "PG7", "SYS_DET_EN", "out", "", "net TG_DET_EN → Q2"),
    (34, "PG6", "TG_DET", "in", "DT", "SDC1 card-detect"),
    (33, "PWRON", "PERON", "pwr", "", ""),
    (32, "5V", "VCC5V", "pwr", "", ""),
    (31, "5V", "VCC5V", "pwr", "", ""),
    (30, "GND", "GND", "pwr", "", ""),
    (29, "GND", "GND", "pwr", "", ""),
    (28, "PG4", "DAT2", "bus", "SDC1", "→ MUX U12"),
    (27, "PG2", "DAT0", "bus", "SDC1", "→ MUX U12"),
    (26, "PG1", "CMD", "bus", "SDC1", "→ MUX U12"),
    (25, "PG3", "DAT1", "bus", "SDC1", "→ MUX U12"),
    (24, "PG0", "CLK", "bus", "SDC1", "22R · → MUX U12"),
    (23, "PG5", "DAT3", "bus", "SDC1", "→ MUX U12"),
]
_bot = ["GND", "GND", "GND", "GND", "USB0_DM", "USB0_DP", "USB1_DM", "USB1_DP",
        "USB2_DM", "USB2_DP", "USB3_DM", "USB3_DP", "AGND", "LINEOUTL", "LINEOUTR",
        "LRADC", "TV_OUT", "RESET", "HHPD", "HSDA", "HSCL", "HCEC", "HTXCN", "HTXCP",
        "HTX0N", "HTX0P", "HTX1N", "HTX1P"]
BOTTOM = []
for i, n in enumerate(_bot):
    if n == "GND":
        BOTTOM.append((73 + i, n, "GND", "pwr", "", ""))
    elif n == "RESET":
        BOTTOM.append((73 + i, n, "RESET", "in", "", "button SW3"))
    else:
        BOTTOM.append((73 + i, n, "", "free", "", ""))

W = 1900
BX0, BX1, BY0, BY1 = 450, 1450, 560, 1460   # module outline
CORNER = 120
out = []
a = out.append


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tag(x0, w, text, kind, fs=12.5):
    fill, stroke, col, dash = STY[kind]
    da = f' stroke-dasharray="{dash}"' if dash else ""
    a(f'<rect x="{x0}" y="-10" width="{w}" height="20" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{da}/>')
    a(f'<text x="{x0 + w / 2}" y="4.5" font-size="{fs}" text-anchor="middle" fill="{col}" font-family="{MONO}">{esc(text)}</text>')


def pinrow(ox, oy, rot, d, p):
    pin, port, fn, kind, badge, note = p
    a(f'<g transform="translate({ox},{oy}) rotate({rot})">')
    # pad + number on the board
    a(f'<circle cx="{-12 * d}" cy="0" r="4.5" fill="#c9a96e"/>')
    anchor = "end" if d > 0 else "start"
    a(f'<text x="{-22 * d}" y="3.5" font-size="10" text-anchor="{anchor}" fill="#cbd5e1" font-family="{MONO}">{pin}</text>')
    a(f'<line x1="{-12 * d}" y1="0" x2="{14 * d}" y2="0" stroke="{FAINT if kind == "free" else "#57534e"}" stroke-width="1.4"/>')

    def place(c, w):  # returns rect x for a tag starting at distance c going outward
        return c if d > 0 else -c - w

    c = 16
    free = kind == "free"
    # port tag
    if free:
        a(f'<rect x="{place(c, 66)}" y="-10" width="66" height="20" rx="4" fill="#ffffff" stroke="#d1d5db"/>')
        a(f'<text x="{place(c, 66) + 33}" y="4.5" font-size="12.5" text-anchor="middle" fill="{FAINT}" font-family="{MONO}">{port}</text>')
    else:
        a(f'<rect x="{place(c, 66)}" y="-10" width="66" height="20" rx="4" fill="#f3f4f6" stroke="#d1d5db"/>')
        a(f'<text x="{place(c, 66) + 33}" y="4.5" font-size="12.5" text-anchor="middle" fill="#374151" font-family="{MONO}">{port}</text>')
    c += 70
    if not free:
        tag(place(c, 128), 128, fn, kind)
        c += 132
        b = badge or DIR.get(kind, "")
        if b:
            a(f'<text x="{c * d + (21 if d > 0 else -21)}" y="4" font-size="10" text-anchor="middle" fill="{MUTED}" font-family="{SANS}" font-weight="600" letter-spacing="0.5">{b}</text>')
        c += 46
    if note:
        anchor = "start" if d > 0 else "end"
        col = FAINT if free else MUTED
        style = ' font-style="italic"' if free else ""
        a(f'<text x="{c * d}" y="4" font-size="11.5" text-anchor="{anchor}" fill="{col}" font-family="{SANS}"{style}>{esc(note)}</text>')
    a('</g>')


a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="HEIGHT" viewBox="0 0 {W} HEIGHT">')
a(f'<rect width="{W}" height="HEIGHT" fill="#fafaf9"/>')

# ---------- header ----------
a(f'<text x="60" y="68" font-size="32" font-weight="700" fill="{INK}" font-family="{SANS}">emmcWriter · DS_H618_Core</text>')
a(f'<text x="60" y="98" font-size="16" fill="{MUTED}" font-family="{SANS}">Pinout: SoC port → function in code (gpiod, gpiochip1) · grey text = schematic net / alt functions</text>')
leg = [("out", "OUT", "output (code)"), ("in", "IN", "input (code)"), ("bus", "SDC0", "bus / peripheral"),
       ("pwr", "5V", "power"), ("pwm", "PWM_RED", "PWM backlight"), ("nc", "HB_LED", "wired, not in code")]
lx = 60
for kind, sample, label in leg:
    a(f'<g transform="translate({lx},140)">')
    tag(0, 70, sample, kind, 11.5)
    a(f'<text x="80" y="4.5" font-size="13" fill="#374151" font-family="{SANS}">{label}</text>')
    a('</g>')
    lx += 80 + len(label) * 7.4 + 34
a(f'<g transform="translate({lx},140)"><rect x="0" y="-10" width="70" height="20" rx="4" fill="#fff" stroke="#d1d5db"/>'
  f'<text x="35" y="4.5" font-size="11.5" text-anchor="middle" fill="{FAINT}" font-family="{MONO}">PI13</text>'
  f'<text x="80" y="4.5" font-size="13" fill="#374151" font-family="{SANS}">free</text></g>')

# ---------- module ----------
a(f'<rect x="{BX0}" y="{BY0}" width="{BX1 - BX0}" height="{BY1 - BY0}" rx="18" fill="#2b3440"/>')
a(f'<rect x="{BX0 + 8}" y="{BY0 + 8}" width="{BX1 - BX0 - 16}" height="{BY1 - BY0 - 16}" rx="12" fill="none" stroke="#3d4855" stroke-width="1.5"/>')
for hx, hy in [(BX0 + 34, BY0 + 34), (BX1 - 34, BY0 + 34), (BX0 + 34, BY1 - 34), (BX1 - 34, BY1 - 34)]:
    a(f'<circle cx="{hx}" cy="{hy}" r="11" fill="#fafaf9" stroke="#c9a96e" stroke-width="3"/>')
cx, cy = (BX0 + BX1) / 2, (BY0 + BY1) / 2
a(f'<rect x="{cx - 120}" y="{cy - 150}" width="240" height="240" rx="10" fill="#1b2129" stroke="#4b5563"/>')
a(f'<text x="{cx}" y="{cy - 40}" font-size="40" font-weight="700" text-anchor="middle" fill="#e5e7eb" font-family="{SANS}">H618</text>')
a(f'<text x="{cx}" y="{cy - 10}" font-size="14" text-anchor="middle" fill="#9ca3af" font-family="{SANS}">Allwinner · 4×A53</text>')
a(f'<circle cx="{cx - 98}" cy="{cy - 128}" r="5" fill="#4b5563"/>')
a(f'<text x="{cx}" y="{cy + 140}" font-size="22" font-weight="600" text-anchor="middle" fill="#e5e7eb" font-family="{SANS}">DS_H618_Core  ·  U13</text>')
a(f'<text x="{cx}" y="{cy + 168}" font-size="13" text-anchor="middle" fill="#9ca3af" font-family="{SANS}">100-pin castellated module</text>')

side_pitch = (BY1 - BY0 - 2 * CORNER) / (len(LEFT) - 1)
for i, p in enumerate(LEFT):
    pinrow(BX0, BY0 + CORNER + i * side_pitch, 0, -1, p)
for i, p in enumerate(RIGHT):
    pinrow(BX1, BY0 + CORNER + i * side_pitch, 0, 1, p)
tb_pitch = (BX1 - BX0 - 2 * CORNER) / (len(TOP) - 1)
for i, p in enumerate(TOP):
    pinrow(BX0 + CORNER + i * tb_pitch, BY0, -90, 1, p)
for i, p in enumerate(BOTTOM):
    pinrow(BX0 + CORNER + i * tb_pitch, BY1, -90, -1, p)

# ---------- block diagram ----------
Y0 = 1900
a(f'<line x1="60" y1="{Y0 - 60}" x2="{W - 60}" y2="{Y0 - 60}" stroke="#e7e5e4" stroke-width="2"/>')
a(f'<text x="60" y="{Y0 - 10}" font-size="26" font-weight="700" fill="{INK}" font-family="{SANS}">Block diagram</text>')
a(f'<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
  f'<path d="M0,0 L10,5 L0,10 z" fill="#57534e"/></marker></defs>')


def box(x, y, w, h, title, lines=(), fill="#ffffff", stroke="#57534e", dark=False):
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    tc = "#f9fafb" if dark else INK
    sc = "#cbd5e1" if dark else MUTED
    a(f'<text x="{x + 16}" y="{y + 28}" font-size="16" font-weight="700" fill="{tc}" font-family="{SANS}">{esc(title)}</text>')
    for k, ln in enumerate(lines):
        mono = ln.startswith("`")
        t = ln.strip("`")
        a(f'<text x="{x + 16}" y="{y + 52 + k * 20}" font-size="13" fill="{sc}" font-family="{MONO if mono else SANS}">{esc(t)}</text>')


def wire(pts, label="", lx=None, ly=None, both=False, dashed=False, anchor="middle"):
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    st = ' marker-start="url(#ar)"' if both else ""
    da = ' stroke-dasharray="6 4"' if dashed else ""
    a(f'<path d="{d}" fill="none" stroke="#57534e" stroke-width="1.6" marker-end="url(#ar)"{st}{da}/>')
    if label:
        for k, ln in enumerate(label.split("\n")):
            a(f'<text x="{lx}" y="{ly + k * 16}" font-size="12.5" text-anchor="{anchor}" fill="#374151" font-family="{MONO}">{esc(ln)}</text>')


# core
CXa, CYa, CW, CH = 720, Y0 + 40, 420, 540
box(CXa, CYa, CW, CH, "U13 · DS_H618_Core  (H618)", [
    "emmcWriter service (Python)",
    "",
    "`HTTP  :8080  remote control",
    "`UDP   :8088  status broadcast / 0.5 s",
    "`IP    192.168.1.(70 + slot)",
    "",
    "`crpi  target → USB3 bridge (big dump)",
    "`copi  target → SoC SDC1",
    "`      boot regions + u-boot",
    "`writeboot / readboot / verifyboot",
    "`buildimg → rootfs + u-boot",
    "`led=N · id=N (beacon)",
    "",
    "`TG_DET_EN → Q2 → TG_DET",
    "`  (SDC1 card-detect emulation)",
], fill="#2b3440", stroke="#2b3440", dark=True)

# left column
LX, LW, LH = 90, 330, 74
lefts = [
    ("Rotary switch U32", ["ES07MP-16RBZ · slot ID 0–7"], "RT_SW_B0..B3", "in", False),
    ("Status LEDs", ["R/Y/G active-high · HB/KP active-low"], "LED_R/Y/G · HB/KP", "out", False),
    ("Gradient backlight", ["PWM1 → red · PWM2 → green"], "PWM_RED · PWM_GREEN", "out", True),
    ("Debug H7 · SW2 FEL · SW3 RST", ["UART0 · buttons"], "DEB_TX/RX · FEL · RESET", "both", False),
    ("LAN · RJ1 HY951180A", ["internal EPHY 100M"], "HTTP / UDP", "both", False),
    ("System eMMC slot U14", ["SoC boot + rootfs · CLK 22R"], "SYS_* · SDC0", "both", False),
]
for k, (title, lines, lab, dr, dashed) in enumerate(lefts):
    y = CYa + 10 + k * 90
    box(LX, y, LW, LH, title, lines, stroke="#a16a2a" if dashed else "#57534e")
    yc = y + LH / 2
    lx = (LX + LW + CXa) / 2
    if dr == "in":
        wire([(LX + LW, yc), (CXa, yc)], lab, lx, yc - 8)
    elif dr == "out":
        wire([(CXa, yc), (LX + LW, yc)], lab, lx, yc - 8, dashed=dashed)
    else:
        wire([(CXa, yc), (LX + LW, yc)], lab, lx, yc - 8, both=True)

# target eMMC chain
MX, MY, MW, MH = 1270, Y0 + 170, 190, 170
box(MX, MY, MW, MH, "U12 MUX", ["TS3A27518E", "`MUX_CH:", "`0 = USB (SD_*)", "`1 = SoC (SDC1)", "10k pull-down → USB"])
EX, EY, EW, EH = 1570, Y0 + 150, 260, 210
box(EX, EY, EW, EH, "Target eMMC  U1", ["PM127 socket · ESD", "", "`U34 TPS2051 → EMMC_VDD", "`  EN  ← MMC_VTG", "`  OC# → MMC_OC", "`EMMC_DET → inserted"])
wire([(MX + MW, MY + 85), (EX, MY + 85)], "EMMC_*", (MX + MW + EX) / 2, MY + 77, both=True)
wire([(CXa + CW, MY + 50), (MX, MY + 50)], "SDC1 bus", (CXa + CW + MX) / 2, MY + 42, both=True)
wire([(CXa + CW, MY + 115), (MX, MY + 115)], "MUX_CH", (CXa + CW + MX) / 2, MY + 107)
wire([(CXa + CW, Y0 + 90), (EX + 130, Y0 + 90), (EX + 130, EY)], "MMC_VTG · MMC_OC · EMMC_DET", (CXa + CW + EX) / 2, Y0 + 82, both=True)

UX, UY, UW, UH = 1270, Y0 + 420, 190, 140
box(UX, UY, UW, UH, "U8 USB3 bridge", ["GL3224 · SD/MMC", "`SD_CD ← Q1 ← CD", "`U36 TPS2051 → VBUS", "`  EN ← USB_BR_EN"])
box(1570, UY + 25, 260, 90, "PC · USB 3.0", ["USB2 connector", "large image dump"])
wire([(MX + MW / 2, MY + MH), (MX + MW / 2, UY)], "SD_*", MX + MW / 2 + 10, MY + MH + 45, both=True, anchor="start")
wire([(UX + UW, UY + 70), (1570, UY + 70)], "USB 3.0", (UX + UW + 1570) / 2, UY + 62, both=True)
wire([(CXa + CW, UY + 85), (UX, UY + 85)], "BR_EN·FB·CD", (CXa + CW + UX) / 2, UY + 77, both=True)

# power row
PY, PH = CYa + CH + 70, 84
a(f'<text x="90" y="{PY - 16}" font-size="14" font-weight="700" fill="{MUTED}" font-family="{SANS}">POWER · ISOLATED INPUTS</text>')
box(90, PY, 330, PH, "CN1 · H1", ["`VIN · SLOT_EN · GND", "`EXT_SW (jig)"])
box(500, PY, 260, PH, "U31 MOCD207", ["`SLOT_EN → ENA", "`EXT_SW  → SW_DET"])
box(840, PY, 260, PH, "U15 TPS5430", ["buck · VIN → VCC5V", "ENA = slot enable"])
box(1180, PY, 260, PH, "U2 SY8089", ["buck · VCC5V → VCC3V3"])
box(1520, PY, 310, PH, "Load switches", ["`U36: VCC5V  → bridge VBUS", "`U34: VCC3V3 → EMMC_VDD"])
wire([(420, PY + 42), (500, PY + 42)])
wire([(760, PY + 42), (840, PY + 42)], "ENA", 800, PY + 34)
wire([(1100, PY + 42), (1180, PY + 42)], "5V", 1140, PY + 34)
wire([(1440, PY + 42), (1520, PY + 42)], "3V3", 1480, PY + 34)
wire([(970, PY), (970, CYa + CH)], "VCC5V → module", 980, PY - 20, anchor="start")
wire([(630, PY), (630, CYa + CH - 20), (CXa, CYa + CH - 20)], "SW_DET → JIG_DET", 640, PY - 20, anchor="start")

H = PY + PH + 60

a('</svg>')
svg = "\n".join(out).replace("HEIGHT", str(H))
with open("emmcWriter_pinout.svg", "w", encoding="utf-8") as f:
    f.write(svg)
print(H)

