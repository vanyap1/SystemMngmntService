import gpiod
import time

# Шукаємо лінії в системі суто за їхніми DT-іменами
net_lo_ntc = gpiod.find_line("rel4")
net_8v_n = gpiod.find_line("rel13")
net_uart = gpiod.find_line("rel12_19")
net_3v3 = gpiod.find_line("rel10")
net_pump = gpiod.find_line("rel8")
net_8v_tp34 = gpiod.find_line("rel11")
net_triac_sim = gpiod.find_line("rel5")
net_fm_en = gpiod.find_line("rel7")
net_prog_dl = gpiod.find_line("rel2_3")
net_AC_en = gpiod.find_line("rel15")
net_prog_vcc = gpiod.find_line("rel1")
net_hi_ntc = gpiod.find_line("rel16")
net_curr_dmm = gpiod.find_line("rel14")
net_fm = gpiod.find_line("u6")
net_btn1 = gpiod.find_line("u7")
net_btn2 = gpiod.find_line("u8")

if not net_lo_ntc or not net_8v_n or not net_uart or not net_3v3 or not net_pump or not net_8v_tp34 or not net_triac_sim or not net_fm_en or not net_prog_dl or not net_AC_en or not net_prog_vcc or not net_hi_ntc or not net_curr_dmm or not net_fm or not net_btn1 or not net_btn2:
    print("dev cannot find line for user button (net_lo_ntc). Check your DT configuration.")
    exit(1)



net_lo_ntc.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_8v_n.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_uart.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_3v3.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_pump.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_8v_tp34.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_triac_sim.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_fm_en.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_prog_dl.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_AC_en.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_prog_vcc.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_hi_ntc.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_curr_dmm.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_fm.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_btn1.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1])
net_btn2.request(consumer="python_app", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[1]) 


print(f"Successfully initialized GPIO lines.")

channels = [
    net_lo_ntc, net_8v_n, net_uart, net_3v3, net_pump, net_8v_tp34,
    net_triac_sim, net_fm_en, net_prog_dl, net_AC_en, net_prog_vcc,
    net_hi_ntc, net_curr_dmm, net_fm, net_btn1, net_btn2,
]

while True:
    net_uart.set_value(0)
    time.sleep(0.1)
    #for ch in channels:
    #    ch.set_value(0)
    #    time.sleep(0.1)
    #    ch.set_value(1)
        
