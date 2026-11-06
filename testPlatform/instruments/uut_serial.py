import serial


uutserialPath = "/dev/serial/by-id/usb-FTDI_USB-RS232_Cable_FT1CPGN5-if00-port0"


class UUTSerial:
    def __init__(self, port=uutserialPath, baudrate=9600, timeout=100):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout)
    
    def open(self):
        if not self.serial.is_open:
            self.serial.open()
    def close(self):
        if self.serial.is_open:
            self.serial.close()

    def writeBytes(self, data: bytes):
        self.serial.write(data)
    def readBytes(self, num_bytes: int) -> bytes:
        return self.serial.read(num_bytes)
    
    def readInvertedBytes(self, num_bytes: int) -> bytes:
        data = self.serial.read(num_bytes)
        return bytes([~b & 0xFF for b in data])

    def writeString(self, data: str):
        self.serial.write(data.encode())
    def readString(self, num_bytes: int) -> str:
        return self.serial.read(num_bytes).decode()
    def writeReadString(self, data: str, num_bytes: int) -> str:
        self.writeString(data)
        return self.readString(num_bytes)
    def flushInput(self):
        self.serial.reset_input_buffer()


if __name__ == "__main__":
    uut_serial = UUTSerial()
    uut_serial.open()
    try:
        while True:
            input("Press Enter to send command...")
            # write 0xF7
            uut_serial.writeBytes(b'\xF7')
            # read 1 byte response
            response = uut_serial.readBytes(1)
            print(f"Received response: {response.hex()}")
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        uut_serial.close()
    