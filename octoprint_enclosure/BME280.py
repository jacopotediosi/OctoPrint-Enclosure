import sys

import bme280
import smbus2

if len(sys.argv) == 2:
    DEVICE = int(sys.argv[1], 16)
else:
    print("-1 | -1")
    sys.exit(1)

# Rev 2 Pi, Pi 2 & Pi 3 & Pi 4 use bus 1
# Rev 1 Pi uses bus 0
bus = smbus2.SMBus(1)


def main():
    try:
        calibration_params = bme280.load_calibration_params(bus, DEVICE)
        data = bme280.sample(bus, DEVICE, calibration_params)

        print(f"{data.temperature:0.1f} | {data.humidity:0.1f}")
    except Exception:
        print("-1 | -1")


if __name__ == "__main__":
    main()
