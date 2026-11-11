import smbus2
import time

# ADS1115 registers
ADS1115_ADDR        = 0x48
ADS1115_REG_CONV    = 0x00
ADS1115_REG_CONFIG  = 0x01

# PGA (full-scale range) mapping: pga value -> (config bits [13:11], full-scale voltage)
PGA_MAP = {
    6144: (0b000, 6.144),
    4096: (0b001, 4.096),
    2048: (0b010, 2.048),
    1024: (0b011, 1.024),
    512:  (0b100, 0.512),
    256:  (0b101, 0.256),
}

# Single-ended MUX settings for channels 0-3
MUX_SINGLE = [0b100, 0b101, 0b110, 0b111]


class ADC:
    def __init__(self, busNum=0, address=ADS1115_ADDR):
        self.bus = smbus2.SMBus(busNum)
        self.address = address

    def read_raw_value(self, channel=0, pga=4096):
        if channel not in range(4):
            raise ValueError(f"Channel must be 0-3, got {channel}")
        if pga not in PGA_MAP:
            raise ValueError(f"PGA must be one of {list(PGA_MAP)}, got {pga}")

        pga_bits, _ = PGA_MAP[pga]
        mux_bits = MUX_SINGLE[channel]

        # Build config register:
        # Bit 15   : OS=1 (start single conversion)
        # Bits 14-12: MUX
        # Bits 11-9 : PGA
        # Bit 8    : MODE=1 (single-shot)
        # Bits 7-5 : DR=100 (128 SPS)
        # Bits 4-0 : comparator defaults
        config = (
            (1 << 15) |
            (mux_bits << 12) |
            (pga_bits << 9) |
            (1 << 8) |
            (0b100 << 5)
        )
        msb = (config >> 8) & 0xFF
        lsb = config & 0xFF
        self.bus.write_i2c_block_data(self.address, ADS1115_REG_CONFIG, [msb, lsb])

        # Wait for conversion (~8 ms for 128 SPS)
        time.sleep(0.01)

        data = self.bus.read_i2c_block_data(self.address, ADS1115_REG_CONV, 2)
        raw = (data[0] << 8) | data[1]
        # Convert from unsigned 16-bit to signed
        if raw > 32767:
            raw -= 65536
        return raw

    def getVoltage(self, channel=0, pga=6144):
        _, fs_voltage = PGA_MAP[pga]
        raw = self.read_raw_value(channel=channel, pga=pga)
        # ADS1115 is 16-bit signed; full scale = 32767 counts
        return raw * fs_voltage / 32767.0

    def close(self):
        self.bus.close()


if __name__ == "__main__":
    adc = ADC(busNum=0)
    try:
        while True:
        
            v = adc.getVoltage(channel=0, pga=6144)
            print(f"CH{0}: {v:.4f} V")
            
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        adc.close()
