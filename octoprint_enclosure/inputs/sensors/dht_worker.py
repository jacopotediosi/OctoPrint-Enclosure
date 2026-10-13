"""Read a DHT sensor and print its temperature and humidity, separated by a space.

Usage: dht_worker.py <DHT11|DHT22> <BCM pin number>

It runs in its own process because importing Adafruit Blinka sets the GPIO numbering of the whole process to BCM.
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
