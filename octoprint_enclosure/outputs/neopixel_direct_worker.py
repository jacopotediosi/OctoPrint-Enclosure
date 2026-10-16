"""Set the color of all the NeoPixels connected directly to a GPIO pin of the Raspberry Pi.

Usage: neopixel_direct_worker.py <BCM pin number> <count> <brightness> <red> <green> <blue> <DMA channel>

It runs in its own process so that it can run as root, which rpi_ws281x requires (except on GPIO 10, which it drives
through SPI).
"""

import sys

from rpi_ws281x import Color, PixelStrip, ws

FREQUENCY_HZ = 800000
INVERT = False
STRIP_TYPE = ws.WS2811_STRIP_GRB
PWM1_PINS = (13, 19)


def main() -> None:
    pin, count, brightness, red, green, blue, dma = (int(arg) for arg in sys.argv[1:])

    channel = 1 if pin in PWM1_PINS else 0

    strip = PixelStrip(count, pin, FREQUENCY_HZ, dma, INVERT, brightness, channel=channel, strip_type=STRIP_TYPE)
    strip.begin()

    color = Color(red, green, blue)
    for i in range(count):
        strip.setPixelColor(i, color)

    strip.show()


if __name__ == "__main__":
    main()
