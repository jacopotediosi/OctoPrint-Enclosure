import sys

import smbus2

if len(sys.argv) == 3:
    DEVICE = int(sys.argv[1], 16)
    bus = smbus2.SMBus(int(sys.argv[2], 16))
else:
    print("-1 | -1")
    sys.exit(1)


def get_all(bus, addr=DEVICE):
    # Set config
    config = [0x08, 0x00]
    bus.write_i2c_block_data(addr, 0xE1, config)
    bus.read_byte(addr)
    # Send MeasureCMD and read data
    measure_cmd = [0x33, 0x00]
    bus.write_i2c_block_data(addr, 0xAC, measure_cmd)
    data = bus.read_i2c_block_data(addr, 0x00, 32)
    temp = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
    ctemp = ((temp * 200) / 1048576) - 50

    hum = ((data[1] << 16) | (data[2] << 8) | data[3]) >> 4
    chum = int(hum * 100 / 1048576)
    return ctemp, chum


def main():
    try:
        temperature, humidity = get_all(bus)
        print(f"{temperature:0.1f} | {humidity:0.1f}")
    except Exception:
        print("-1 | -1")


if __name__ == "__main__":
    main()
