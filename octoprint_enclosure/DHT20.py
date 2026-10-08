import sys

import smbus2


class DHT20Error(Exception):
    """Base class for exception."""


if len(sys.argv) == 2 or len(sys.argv) == 3:
    address = int(sys.argv[1], 16)
    bus_num = int(sys.argv[2], 16) if len(sys.argv) == 3 else 1
else:
    print("-1 | -1")
    sys.exit(1)


sensor = smbus2.SMBus(bus_num)

data = sensor.read_i2c_block_data(address, 0x71, 1)
if (data[0] | 0x08) == 0:
    raise DHT20Error("Initialization error")


def get_value(bus):
    bus.write_i2c_block_data(address, 0xAC, [0x33, 0x00])
    data = bus.read_i2c_block_data(address, 0x71, 7)
    t_raw = ((data[3] & 0xF) << 16) + (data[4] << 8) + data[5]
    h_raw = ((data[3] & 0xF0) << 4) + (data[1] << 12) + (data[2] << 4)
    temp = 200 * float(t_raw) / 2**20 - 50
    humi = 100 * float(h_raw) / 2**20
    return temp, humi


def main():
    try:
        temperature, humidity = get_value(sensor)
        print(f"{temperature:0.1f} | {humidity:0.1f}")
    except Exception:
        print("-1 | -1")


if __name__ == "__main__":
    main()
