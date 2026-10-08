import sys
import time

import smbus2

if len(sys.argv) == 2 or len(sys.argv) == 3:
    address = int(sys.argv[1], 16)
    bus_num = int(sys.argv[2], 16) if len(sys.argv) == 3 else 1
else:
    print("-1 | -1")
    sys.exit(1)

# Get I2C bus
bus = smbus2.SMBus(bus_num)

# SI7021 address, 0x40(64)
# 		0xF5(245)	Select Relative Humidity NO HOLD master mode
bus.write_byte(address, 0xF5)

time.sleep(0.3)

# SI7021 address, 0x40(64)
# Read data back, 2 bytes, Humidity MSB first
data0 = bus.read_byte(address)
data1 = bus.read_byte(address)

# Convert the data
humidity = ((data0 * 256 + data1) * 125 / 65536.0) - 6

time.sleep(0.3)

# SI7021 address, 0x40(64)
# 		0xF3(243)	Select temperature NO HOLD master mode
bus.write_byte(address, 0xF3)

time.sleep(0.3)

# SI7021 address, 0x40(64)
# Read data back, 2 bytes, Temperature MSB first
data0 = bus.read_byte(address)
data1 = bus.read_byte(address)

# Convert the data
c_temp = ((data0 * 256 + data1) * 175.72 / 65536.0) - 46.85

print(f"{c_temp:0.1f} | {humidity:0.1f}")
