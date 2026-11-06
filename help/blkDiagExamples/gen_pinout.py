# Generates H618_pinout.svg: DS_H618_Core pins with port name (inside) and project function (outside)

COL = {
    "enc":  "#7b3fc4",  # rotary ID encoder
    "pwm":  "#d6157a",  # chosen PWM
    "emmc0": "#1f6fd1", # eMMC #1 (SDC0, SYS_*)
    "emmc1": "#0e9488", # eMMC #2 (SDC1, DAT*)
    "ctrl": "#374151",  # control / detect
    "led":  "#d97706",  # LEDs
    "eth":  "#15803d",  # Ethernet
    "dbg":  "#92400e",  # debug UART
    "pwr":  "#dc2626",  # power / GND
    "free": "#9ca3af",  # not connected
}

# (pin, port, function, group, alt-for-free)
LEFT = [
    (51, "PI7", "ID_B3 (8)", "enc", ""),
    (52, "PI8", "ID_B2 (4)", "enc", ""),
    (53, "PI9", "ID_B1 (2)", "enc", ""),
    (54, "PI10", "ID_B0 (1)", "enc", ""),
    (55, "PI11", "PWM_1", "pwm", ""),
    (56, "PI12", "PWM_2", "pwm", ""),
    (57, "PI13", "", "free", "PWM3 / UART4_TX"),
    (58, "PI14", "", "free", "PWM4 / UART4_RX"),
    (59, "PI15", "USB_BR_EN", "ctrl", ""),
    (60, "PI16", "USB_BR_FB", "ctrl", ""),
    (61, "PF6", "SYS_DET", "emmc0", ""),
    (62, "PF0", "SYS_D1", "emmc0", ""),
    (63, "PF1", "SYS_D0", "emmc0", ""),
    (64, "PF2", "SYS_CLK", "emmc0", ""),
    (65, "PF3", "SYS_CMD", "emmc0", ""),
    (66, "PF4", "SYS_D3", "emmc0", ""),
    (67, "PF5", "SYS_D2", "emmc0", ""),
    (68, "GND", "GND", "pwr", ""),
    (69, "3V3-OUT", "3V3_OUT", "pwr", ""),
    (70, "GND", "GND", "pwr", ""),
    (71, "1V8-OUT", "", "free", "1V8 out"),
    (72, "GND", "GND", "pwr", ""),
]
RIGHT = [
    (22, "PG14", "CD", "ctrl", ""),
    (21, "PG11", "MUX_CH", "ctrl", ""),
    (20, "PG12", "EMMC_DET", "ctrl", ""),
    (19, "PG13", "SW_DET", "ctrl", ""),
    (18, "PH10", "MMC_OC", "ctrl", ""),
    (17, "PH9", "MMC_VTG", "ctrl", ""),
    (16, "PH8", "HB_LED", "led", ""),
    (15, "PH7", "KP_LED", "led", ""),
    (14, "PH6", "R_LED", "led", ""),
    (13, "PH5", "Y_LED", "led", ""),
    (12, "PH4", "G_LED", "led", ""),
    (11, "PH3", "LNK_ETH", "eth", ""),
    (10, "PH2", "SPD_ETH", "eth", ""),
    (9, "PH1", "DEB_RX", "dbg", ""),
    (8, "PH0", "DEB_TX", "dbg", ""),
    (7, "FEL", "FEL", "ctrl", ""),
    (6, "EPHY_TXP", "TXP_ETH", "eth", ""),
    (5, "EPHY_TXN", "TXN_ETH", "eth", ""),
    (4, "EPHY_RXP", "RXP_ETH", "eth", ""),
    (3, "EPHY_RXN", "RXN_ETH", "eth", ""),
    (2, "HTX2P", "", "free", "HDMI"),
    (1, "HTX2N", "", "free", "HDMI"),
]
TOP = [
    (50, "PI6", "", "free", "UART2_RX/TWI0_SDA"),
    (49, "PI5", "", "free", "UART2_TX/TWI0_SCK"),
    (48, "PI4", "", "free", "I2S0_DIN0"),
    (47, "PI3", "", "free", "I2S0_DOUT0"),
    (46, "PI2", "", "free", "I2S0_LRCK"),
    (45, "PI1", "", "free", "I2S0_BCLK"),
    (44, "PI0", "", "free", "I2S0_MCLK"),
    (43, "PG17", "", "free", "UART2_RTS"),
    (42, "PG19", "", "free", "PWM1"),
    (41, "PG18", "", "free", "UART2_CTS"),
    (40, "PG16", "", "free", "UART2_RX/TWI4_SDA"),
    (39, "PG15", "", "free", "UART2_TX/TWI4_SCK"),
    (38, "PG10", "", "free", "I2S2_MCLK"),
    (37, "PG8", "", "free", "UART1_RTS"),
    (36, "PG9", "", "free", "UART1_CTS"),
    (35, "PG7", "TG_DET_EN", "ctrl", ""),
    (34, "PG6", "TG_DET", "ctrl", ""),
    (33, "PWRON", "PERON", "ctrl", ""),
    (32, "5V", "VCC5V", "pwr", ""),
    (31, "5V", "VCC5V", "pwr", ""),
    (30, "GND", "GND", "pwr", ""),
    (29, "GND", "GND", "pwr", ""),
    (28, "PG4", "DAT2", "emmc1", ""),
    (27, "PG2", "DAT0", "emmc1", ""),
    (26, "PG1", "CMD", "emmc1", ""),
    (25, "PG3", "DAT1", "emmc1", ""),
    (24, "PG0", "CLK (22R)", "emmc1", ""),
    (23, "PG5", "DAT3", "emmc1", ""),
]
_bot = ["GND", "GND", "GND", "GND", "USB0_DM", "USB0_DP", "USB1_DM", "USB1_DP",
        "USB2_DM", "USB2_DP", "USB3_DM", "USB3_DP", "AGND", "LINEOUTL", "LINEOUTR",
        "LRADC", "TV_OUT", "RESET", "HHPD", "HSDA", "HSCL", "HCEC", "HTXCN", "HTXCP",
        "HTX0N", "HTX0P", "HTX1N", "HTX1P"]
BOTTOM = []
for i, name in enumerate(_bot):
    pin = 73 + i
    if name == "GND":
        BOTTOM.append((pin, name, "GND", "pwr", ""))
    elif name == "RESET":
        BOTTOM.append((pin, name, "RESET", "ctrl", ""))
    else:
        BOTTOM.append((pin, name, "", "free", ""))

W, H = 1800, 1360
CX0, CX1, CY0, CY1 = 430, 1370, 360, 1150
STUB = 34
out = []
a = out.append
a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
  'font-family="Consolas, \'DejaVu Sans Mono\', monospace">')
a(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
a('<text x="40" y="52" font-size="30" font-weight="bold" fill="#111827" font-family="Segoe UI, Arial">'
  'DS_H618_Core (U13) — pinout / project functions</text>')
a('<text x="40" y="82" font-size="16" fill="#4b5563" font-family="Segoe UI, Arial">'
  'Inside the box: SoC port  ·  Outside: net / function in this project  ·  grey = not connected (alt functions shown)</text>')
a(f'<rect x="{CX0}" y="{CY0}" width="{CX1-CX0}" height="{CY1-CY0}" fill="#f9fafb" stroke="#111827" stroke-width="3"/>')


def fn_text(fn, grp, alt):
    return (fn, "bold") if grp != "free" else ((("· " + alt) if alt else "nc"), "normal")


def side(pins, left):
    pitch = (CY1 - CY0 - 140) / (len(pins) - 1)
    for i, (pin, port, fn, grp, alt) in enumerate(pins):
        y = CY0 + 70 + i * pitch
        c = COL[grp]
        if left:
            x0, x1 = CX0 - STUB, CX0
            a(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{c}" stroke-width="2.5"/>')
            a(f'<text x="{x0+STUB/2}" y="{y-4}" font-size="11" text-anchor="middle" fill="#6b7280">{pin}</text>')
            a(f'<text x="{CX0+8}" y="{y+5}" font-size="15" fill="#111827">{port}</text>')
            t, wgt = fn_text(fn, grp, alt)
            a(f'<text x="{x0-8}" y="{y+5}" font-size="16" font-weight="{wgt}" text-anchor="end" fill="{c}">{t}</text>')
            if grp == "pwm":
                a(f'<rect x="{x0-150}" y="{y-12}" width="{STUB+150+80}" height="24" rx="5" fill="none" stroke="{c}" stroke-width="2" stroke-dasharray="5 3"/>')
        else:
            x0, x1 = CX1, CX1 + STUB
            a(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{c}" stroke-width="2.5"/>')
            a(f'<text x="{x0+STUB/2}" y="{y-4}" font-size="11" text-anchor="middle" fill="#6b7280">{pin}</text>')
            a(f'<text x="{CX1-8}" y="{y+5}" font-size="15" text-anchor="end" fill="#111827">{port}</text>')
            t, wgt = fn_text(fn, grp, alt)
            a(f'<text x="{x1+8}" y="{y+5}" font-size="16" font-weight="{wgt}" fill="{c}">{t}</text>')


def row(pins, top):
    pitch = (CX1 - CX0 - 160) / (len(pins) - 1)
    for i, (pin, port, fn, grp, alt) in enumerate(pins):
        x = CX0 + 80 + i * pitch
        c = COL[grp]
        t, wgt = fn_text(fn, grp, alt)
        if top:
            y0, y1 = CY0 - STUB, CY0
            a(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="{c}" stroke-width="2.5"/>')
            a(f'<text transform="translate({x-3},{y0+STUB/2}) rotate(-90)" font-size="10" text-anchor="middle" fill="#6b7280">{pin}</text>')
            a(f'<text transform="translate({x+5},{CY0+8}) rotate(-90)" font-size="14" text-anchor="end" fill="#111827">{port}</text>')
            a(f'<text transform="translate({x+5},{y0-8}) rotate(-90)" font-size="15" font-weight="{wgt}" fill="{c}">{t}</text>')
        else:
            y0, y1 = CY1, CY1 + STUB
            a(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="{c}" stroke-width="2.5"/>')
            a(f'<text transform="translate({x-3},{y0+STUB/2}) rotate(-90)" font-size="10" text-anchor="middle" fill="#6b7280">{pin}</text>')
            a(f'<text transform="translate({x+5},{CY1-8}) rotate(-90)" font-size="14" fill="#111827">{port}</text>')
            a(f'<text transform="translate({x+5},{y1+8}) rotate(-90)" font-size="15" font-weight="{wgt}" text-anchor="end" fill="{c}">{t}</text>')


side(LEFT, True)
side(RIGHT, False)
row(TOP, True)
row(BOTTOM, False)

# notes inside the chip
nx, ny = 600, 580
notes = [
    ("DS_H618_Core  (Allwinner H616/H618)", "#111827", 22, "bold"),
    ("", "#111827", 10, "normal"),
    ("ID_B0..B3  — rotary binary encoder U32 (ES07MP-16RBZ)", COL["enc"], 15, "bold"),
    ("   device ID 0–7 = B2..B0; common → 3V3, 10k pull-down", COL["enc"], 14, "normal"),
    ("SYS_*  (SDC0, PF0–PF6) — eMMC #1 in SD mode", COL["emmc0"], 15, "bold"),
    ("DAT*/CMD/CLK  (SDC1, PG0–PG5) — eMMC #2 in SD mode", COL["emmc1"], 15, "bold"),
    ("PWM_1 = PI11 (PWM1),  PWM_2 = PI12 (PWM2)", COL["pwm"], 15, "bold"),
    ("   spare PWM: PI13 (PWM3), PI14 (PWM4)", COL["pwm"], 14, "normal"),
    ("DEB_RX/TX = UART0 debug console", COL["dbg"], 15, "bold"),
    ("Ethernet = internal EPHY (RGMII pins unused)", COL["eth"], 15, "bold"),
]
yy = ny
for text, c, fs, wgt in notes:
    a(f'<text x="{nx}" y="{yy}" font-size="{fs}" font-weight="{wgt}" fill="{c}" font-family="Segoe UI, Arial">{text}</text>')
    yy += fs + 14

# legend
legend = [("enc", "ID encoder"), ("pwm", "PWM (selected)"), ("emmc0", "eMMC #1 / SDC0"),
          ("emmc1", "eMMC #2 / SDC1"), ("ctrl", "control / detect"), ("led", "LED"),
          ("eth", "Ethernet"), ("dbg", "debug UART"), ("pwr", "power"), ("free", "not connected")]
lx, ly = 40, 1320
for i, (g, name) in enumerate(legend):
    x = lx + i * 172
    a(f'<rect x="{x}" y="{ly-13}" width="16" height="16" rx="3" fill="{COL[g]}"/>')
    a(f'<text x="{x+22}" y="{ly}" font-size="15" fill="#111827" font-family="Segoe UI, Arial">{name}</text>')

a('</svg>')
with open("H618_pinout.svg", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("ok")

