
import time

import socket
from enum import Enum
from threading import Thread

HOST_IP = '192.168.1.107'
TX_PORT = 5839
RX_PORT = 5832

GPIO_IP = '192.168.1.99'
GPIO_TX_PORT = 53001
GPIO_RX_PORT = 53002

#sudo nano /etc/systemd/system/ioServ.service
'''

[Unit]
Description=My Custom Service
After=network-online.target
Wants=network-online.target


[Service]
ExecStartPre=/bin/sh -c 'echo "[  \033[33mRUN\033[0m  ] Wait 10 seconds" > /dev/tty1'
ExecStartPre=/bin/sleep 10
ExecStartPre=/bin/sh -c 'echo -e "\033c" > /dev/tty1'
ExecStartPre=/bin/sh -c 'echo "[  \033[33mRUN\033[0m  ] Wait 10 seconds" > /dev/tty1'
ExecStartPre=/bin/sh -c 'echo "IP addresses:" > /dev/tty1'
ExecStartPre=/bin/sh -c 'ip addr show | grep -oP "(?<=inet\s)\d+\.\d+\.\d+\.\d+" >> /dev/tty1'



ExecStart=/usr/bin/python3 /home/vanya/ioServer/ioServer.py
Restart=always
User=vanya

[Install]
WantedBy=multi-user.target

'''
# sudo systemctl start/restart ioServ
# sudo systemctl enable ioServ
# sudo systemctl status ioServ


class MainLoop:
    testVar = "rrr"
    def __init__(self):
        print("Start")
        self.udp_worker = UdpWorkerSlave(self)
        self.udpMaster = UdpWorkerMaster(self)
        self.newDataAvailable = False
        self.loop()

    def loop(self):
        while True:
            if(self.newDataAvailable):
                print(f"Mainloop, {self.testVar}")
                self.newDataAvailable = False
            
    def setIOValue(self, new_value):
        self.testVar = new_value
        self.newDataAvailable = True
        return (f"ok; {new_value}")







class UdpWorkerSlave(Thread):
    counter = 0
    def __init__(self, main_loop_instance):
        self.main_loop = main_loop_instance
        Thread.__init__(self)
        self.daemon = True
        self.start()

    def run(self):
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.bind(('', RX_PORT))
        #udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Разрешить прием широковещательных сообщений

        while True:
            data, addr = udp_socket.recvfrom(1024)
            try:
                decoded_data = data.decode('utf-8')
                result = self.main_loop.setIOValue(decoded_data)
                udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                udp_socket.sendto(result.encode('utf-8'), (HOST_IP, TX_PORT))

            except UnicodeDecodeError:
                print("data decode error")  

class UdpWorkerMaster(Thread):
    counter = 0
    def __init__(self, main_loop_instance):
        self.main_loop = main_loop_instance
        Thread.__init__(self)
        self.daemon = True
        self.start()

    def run(self):
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.bind(('', GPIO_RX_PORT))
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)  # Разрешить прием широковещательных сообщений
        udp_socket.settimeout(3)
        while True:
            udp_socket.sendto(f"MEAS:CURR?; {self.counter}".encode('utf-8'), (GPIO_IP, GPIO_TX_PORT))
            
            try:
                data, addr = udp_socket.recvfrom(1024)
                try:
                    decoded_data = data.decode('utf-8')
                    #print(decoded_data)
                except UnicodeDecodeError:
                    print("data decode error")
            except socket.timeout:
                print("recvfrom timeout")
            
            self.counter += 1
            time.sleep(0.1)

if __name__ == '__main__':
    main = MainLoop()
    #udp_worker_master = UdpWorkerMaster(main)
    #udp_worker_master.join()