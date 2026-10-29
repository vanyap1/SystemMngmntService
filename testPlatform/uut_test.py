
import time
import gpiod
from stm8_flash import STM8Flasher
from uut_serial import UUTSerial
from dmm2 import FS9922DMM
from testStrategy import TestStrategy
from adc import ADC

fwDir = "/home/vanya/vtp/fw"
test_FW = "VTP1EleReDesignEOLT_V_4.hex"
final_FW = "VTP1EleReDesign_V_7_4_Program.hex"
final_data = "VTP1EleReDesign_V_7_4_Data.hex"
uutChip = "STM8S003F3"

uutSerialPath = "/dev/serial/by-id/usb-FTDI_USB-RS232_Cable_FT1CPH3U-if00-port0"
uutSerialBaudrate = 9600
uutSerialTimeout = 0.1


dmmSerialPath = "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AL058YDQ-if00-port0"


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




if __name__ == "__main__":
    print("Запуск тесту GPIO...")
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
    
    flasher = STM8Flasher(fw_dir=fwDir, chip=uutChip)
    uut_serial = UUTSerial(port=uutSerialPath, baudrate=uutSerialBaudrate, timeout=uutSerialTimeout)
    uut_serial.open()
    dmm = FS9922DMM(port=dmmSerialPath)
    #adc = ADC(busNum=0)
    ts = TestStrategy()

    def flowmeterTest(pulseCount: int) -> int:
        # send cmd to uut - 0x7B
        # delay 1 sec
        # send cmd to uut - 0xBF
        # generate 20 pulses on net_fm
        # read inverted byte by cmd - 0xBE
        uut_serial.writeBytes(b'\x7B')
        time.sleep(0.5)
        uut_serial.writeBytes(b'\xBF')
        time.sleep(1)
        for _ in range(pulseCount):
            net_fm.set_value(1)
            time.sleep(0.05)
            net_fm.set_value(0)
            time.sleep(0.05)
        net_fm.set_value(1)
        uut_serial.writeBytes(b'\xBE')
        response = uut_serial.readInvertedBytes(1)
        return response[0] if response else -1
    

    def key1Test() -> bool:
        # send cmd to uut - 0xEF
        # emulate key press on net_btn1 (0 pressed, 1 released)
        # pass res - x18
        # emulate key release on net_btn1
        # send cmd to uut - 0x19
        # finish test, return True if res == 0x18, else False
        uut_serial.writeBytes(b'\xEF')
        net_btn1.set_value(0)
        time.sleep(0.2)
        pressedRes = uut_serial.readInvertedBytes(1)
        net_btn1.set_value(1)
        time.sleep(0.2)
        releasedRes = uut_serial.readInvertedBytes(1)
        uut_serial.writeBytes(b'\xFB')
        return pressedRes[0] == 0x18 and releasedRes[0] == 0x19 if pressedRes and releasedRes else False

    def key2Test() -> bool:
        # send cmd to uut - 0xEE
        # emulate key press on net_btn2 (0 pressed, 1 released)
        # pass res - x18
        # emulate key release on net_btn2
        # send cmd to uut - 0x19
        # finish test, return True if res == 0x18, else False
        uut_serial.writeBytes(b'\xEE')
        net_btn2.set_value(0)
        time.sleep(0.2)
        pressedRes = uut_serial.readInvertedBytes(1)
        net_btn2.set_value(1)
        time.sleep(0.2)
        releasedRes = uut_serial.readInvertedBytes(1)
        uut_serial.writeBytes(b'\xFB')
        return pressedRes[0] == 0x1A and releasedRes[0] == 0x1B if pressedRes and releasedRes else False
        
    def checkNTC(dummyNTC: bool = False) -> int:
        if dummyNTC:
            net_lo_ntc.set_value(0)
            net_hi_ntc.set_value(1)
        else:
            net_lo_ntc.set_value(1)
            net_hi_ntc.set_value(0)


        for _ in range(5):
            uut_serial.writeBytes(b'\xDF')
            response = uut_serial.readInvertedBytes(1)
            #print(f"NTC check response: {response[0] if response else 'None'}")
            time.sleep(0.4)
        net_hi_ntc.set_value(1)
        net_lo_ntc.set_value(1)
        return response[0] if response else -1

    def get3v3Volt() -> float:
        net_3v3.set_value(0)
        time.sleep(3)
        dmmVoltage = dmm.getVolt()
        net_3v3.set_value(1)
        return dmmVoltage

    def getMinus8Volt() -> float:
        net_8v_n.set_value(0)
        time.sleep(3)
        dmmVoltage = dmm.getVolt()
        net_8v_n.set_value(1)
        return dmmVoltage


    ts.logResult("UUT UART disconnected", net_uart.set_value(1) is None, "OK")
    ts.logResult("StLink VCC off", net_prog_vcc.set_value(1) is None, "OK")
    ts.logResult("AC power disabled", net_AC_en.set_value(1) is None, "OK")
    time.sleep(0.5)
    try:
        while True:
            input("Press Enter to run test sequence...")
            #print horizontal green line
            print("\n\r\033[92m" + "-" * 60 + "\033[0m")
            
            def sequence():
                ts.logResult("StLink VCC on", net_prog_vcc.set_value(0) is None, "OK")
                net_prog_dl.set_value(0)
                ts.logResult("StLink DL on", net_prog_dl.set_value(0) is None, "OK")
                time.sleep(0.1)

                #input("Press Enter to start flashing test firmware...")


                ts.logResult("Erase chip", flasher.erase_chip(), "Chip erased successfully")
                ts.logResult("Flash chip", flasher.flash(test_FW), "Chip flashed successfully")
                ts.logResult("Verify flash", flasher.verify(test_FW), "Chip verified successfully")


                ts.logResult("StLink VCC off", net_prog_vcc.set_value(1) is None, "")
                ts.logResult("StLink DL off", net_prog_dl.set_value(1) is None, "")


                time.sleep(2.5)
                #ts.logResult("StLink VCC on", net_prog_vcc.set_value(0) is None, "OK")

                ts.logResult("AC power enabled", net_AC_en.set_value(0) is None, "OK")
                ts.logResult("UUT UART connected", net_uart.set_value(0) is None, "OK")
                time.sleep(.8)

                response = b''
                for _ in range(3):
                    uut_serial.flushInput()
                    uut_serial.writeBytes(b'\xF7')
                    tmpRes = uut_serial.readInvertedBytes(1)
                    if tmpRes:
                        response = tmpRes
                        break
                    time.sleep(0.1)
                uut_serial.flushInput()
                uut_serial.writeBytes(b'\xF7')
                ts.numericLimitTestInclusive("UUT response", int.from_bytes(uut_serial.readInvertedBytes(1), 'big'), 0x04, 0x04, "")
                uut_serial.writeBytes(b'\x5F')
                ts.numericLimitTestInclusive("Zero cross", int.from_bytes(uut_serial.readInvertedBytes(1), 'big'), 193, 193, "")

                #ts.numericLimitTest("LED1 ON state", round(adc.getVoltage(channel=0, pga=6144), 2), 0.01, 1.1, "v")
                #ts.numericLimitTest("LED1 ON state", round(adc.getVoltage(channel=0, pga=6144), 2), 0.01, 1.1, "v")
                #flowmeter test
                ts.numericLimitTest("Flowmeter pulse count", flowmeterTest(20), 19, 21, "pulses")
                ts.logResult("Key1 test", key1Test(), "OK")
                ts.logResult("Key2 test", key2Test(), "OK")
                ts.numericLimitTest("NTC HI", checkNTC(dummyNTC=True), 207, 227, "OK")
                ts.numericLimitTest("NTC LO", checkNTC(dummyNTC=False), 125, 145, "OK")
                ts.numericLimitTest("Minus 8V", getMinus8Volt(), 7.3, 8.3, "V")
                ts.numericLimitTest("3.3V", get3v3Volt(), 3.1, 3.5, "V")
                ts.logResult("UUT UART disconnected", net_uart.set_value(1) is None, "OK")
                net_AC_en.set_value(1)
                time.sleep(0.5)
                #program final firmware
                ts.logResult("StLink VCC on", net_prog_vcc.set_value(0) is None, "OK")
                net_prog_dl.set_value(0)
                ts.logResult("StLink DL on", net_prog_dl.set_value(0) is None, "OK")
                time.sleep(0.1)
                ts.logResult("Flash final FW", flasher.flash(final_FW), "Chip flashed successfully")
                ts.logResult("Verify final FW", flasher.verify(final_FW), "Chip verified successfully")
                ts.logResult("StLink VCC off", net_prog_vcc.set_value(1) is None, "")
                ts.logResult("StLink DL off", net_prog_dl.set_value(1) is None, "")


                net_AC_en.set_value(0)
                time.sleep(0.5)
                #ts.numericLimitTest("LED1 OFF state", round(adc.getVoltage(channel=0, pga=6144), 2), 4.2, 5.2, "v")
                #ts.numericLimitTest("LED1 OFF state", round(adc.getVoltage(channel=0, pga=6144), 2), 4.2, 5.2, "v")

            def finalize():
                # Safe fixture state - runs after pass, fail (stop on fail), exception or Stop
                ts.logResult("UUT UART disconnected", net_uart.set_value(1) is None, "OK")
                ts.logResult("StLink VCC off", net_prog_vcc.set_value(1) is None, "OK")
                ts.logResult("StLink DL off", net_prog_dl.set_value(1) is None, "OK")
                ts.logResult("AC power disabled", net_AC_en.set_value(1) is None, "OK")
                ts.logResult("Cleanup test", True, "OK")

            ts.run(sequence, finalize)

            print("\n\r\033[92m" + "-" * 60 + "\033[0m\n")


    
    


    except KeyboardInterrupt:
        print("\nТест GPIO завершено користувачем.")
    except EOFError:
        # stdin closed: single run started from the web test runner
        pass