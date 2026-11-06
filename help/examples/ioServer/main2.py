import time
import threading
import socket
from enum import Enum
#from support import ExternalHelper

HOST_BROADCAST = '192.168.1.107'
TX_PORT = 5839
RX_PORT = 5832


class MainThread():
    def __init__(self):
        pass

    def run(self): 
        while True:
            msg = "message"
            data=msg.encode('utf-8')
            #udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            #udp_socket.sendto(data, (HOST_BROADCAST, TX_PORT))
            #udp_socket.close()
            print("-")
            time.sleep(3)


def udp_listener():
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind(('', RX_PORT))

    while True:
        data, addr = udp_socket.recvfrom(1024)
        try:
            decoded_data = data.decode('utf-8')

            msg = f"message + {decoded_data}" 
            ansver_data=msg.encode('utf-8')
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.sendto(ansver_data, (HOST_BROADCAST, TX_PORT))

            print(addr, decoded_data)
        except UnicodeDecodeError:
            print("data decode error")    




if __name__ == '__main__':
    main = MainThread()
    main_thread = threading.Thread(target=main.run)
    udpListener = threading.Thread(target=udp_listener)

    main_thread.start()
    udpListener.start()

    main_thread.join()
    udpListener.join()