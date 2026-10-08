import ctypes
import struct
import sys

import spidev


def main():
    # Get bus address if provided or use default address
    SPI_DEVICE = 0
    if len(sys.argv) >= 2:
        SPI_DEVICE = int(sys.argv[1], 0)

    if not 0 <= SPI_DEVICE <= 1:
        raise ValueError("Invalid address value")

   # Raspberry Pi hardware SPI configuration.
    SPI_PORT   = 0
    spi = spidev.SpiDev()
    spi.open(SPI_PORT, SPI_DEVICE)
    spi.max_speed_hz = 5000000
    spi.mode = 0
    spi.lsbfirst = False

    # Read 32 bits and decode them as the deprecated Adafruit_MAX31855.readTempC() did
    raw = spi.readbytes(4)
    if len(raw) != 4:
        raise RuntimeError('Did not read expected number of bytes from device!')
    v = raw[0] << 24 | raw[1] << 16 | raw[2] << 8 | raw[3]
    if v & 0x7:
        # Fault bits set
        temp = float('NaN')
    elif v & 0x80000000:
        # Negative value, take 2's complement
        temp = ((v >> 18) - 16384) * 0.25
    else:
        temp = (v >> 18) * 0.25

    print('{0:0.1f}'.format(temp))

if __name__ == "__main__":
    main()
