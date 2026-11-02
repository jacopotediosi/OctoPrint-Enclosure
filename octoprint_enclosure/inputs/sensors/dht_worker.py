"""Read a DHT sensor and print its temperature and humidity, separated by a space.

Usage: dht_worker.py <DHT11|DHT22> <BCM pin number>

It runs in its own process because adafruit_dht reads the pulses through a helper process (libgpiod_pulsein) it talks
to over a SysV message queue, waiting with no timeout: if the helper dies or hangs, the caller blocks forever. A
process of its own gets killed by the timeout of the plugin, so a hang costs one reading, and leaves no helper
process inside OctoPrint.
"""

import sys
import time

import adafruit_dht
from microcontroller import Pin

MODELS = {"DHT11": adafruit_dht.DHT11, "DHT22": adafruit_dht.DHT22}

ATTEMPTS = 4
FAILED_ATTEMPT_DELAY_SECONDS = 2
EMPTY_ATTEMPT_DELAY_SECONDS = 1


def main() -> None:
    model, pin = sys.argv[1], int(sys.argv[2])
    dht_device = MODELS[model](Pin(pin))
    error = "no data"
    try:
        # Reads fail quite often, retry as suggested by the adafruit_dht docs
        for _ in range(ATTEMPTS):
            try:
                humidity = dht_device.humidity
                temperature = dht_device.temperature
            except RuntimeError as exception:
                error = str(exception)
                time.sleep(FAILED_ATTEMPT_DELAY_SECONDS)
                continue

            if humidity is not None and temperature is not None:
                print(temperature, humidity)
                return

            time.sleep(EMPTY_ATTEMPT_DELAY_SECONDS)
    finally:
        dht_device.exit()

    sys.exit(f"No valid reading after {ATTEMPTS} attempts, the last error was: {error}")


if __name__ == "__main__":
    main()
