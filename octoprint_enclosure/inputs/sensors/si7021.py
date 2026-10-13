from __future__ import annotations

import time
from dataclasses import dataclass

from smbus2 import SMBus, i2c_msg
from typing_extensions import override

from octoprint_enclosure.utils import parse_hex

from .base import Reading, Sensor

MEASURE_HUMIDITY_COMMAND = 0xF5
MEASURE_TEMPERATURE_COMMAND = 0xF3

# Maximum measurement times of the SHT21, the slowest of the SI7021 clones
MEASURE_HUMIDITY_DELAY_MS = 30
MEASURE_TEMPERATURE_DELAY_MS = 85

TEMP_HUM_BYTES = 2


@dataclass(frozen=True)
class Si7021Config:
    """The configuration of an SI7021 sensor."""

    temp_sensor_address: int
    """The I2C address of the sensor."""

    temp_sensor_i2cbus: int
    """The number of the I2C bus."""


class Si7021Sensor(Sensor[Si7021Config]):
    """An SI7021 temperature and humidity sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Si7021Config:
        return Si7021Config(
            temp_sensor_address=parse_hex(settings["temp_sensor_address"]),
            temp_sensor_i2cbus=int(str(settings["temp_sensor_i2cbus"])),
        )

    @override
    def read(self) -> Reading:
        address = self.config.temp_sensor_address
        try:
            with SMBus(self.config.temp_sensor_i2cbus) as bus:
                # Measure and receive the humidity
                bus.write_byte(address, MEASURE_HUMIDITY_COMMAND)
                time.sleep(MEASURE_HUMIDITY_DELAY_MS / 1000)
                humidity_msg = i2c_msg.read(address, TEMP_HUM_BYTES)
                bus.i2c_rdwr(humidity_msg)

                # Measure and receive the temperature
                bus.write_byte(address, MEASURE_TEMPERATURE_COMMAND)
                time.sleep(MEASURE_TEMPERATURE_DELAY_MS / 1000)
                temperature_msg = i2c_msg.read(address, TEMP_HUM_BYTES)
                bus.i2c_rdwr(temperature_msg)

                raw_humidity = int.from_bytes(bytes(humidity_msg), "big")
                raw_temperature = int.from_bytes(bytes(temperature_msg), "big")

                # Formulas from the datasheet
                humidity = raw_humidity / 2**16 * 125 - 6
                temperature = raw_temperature / 2**16 * 175.72 - 46.85
        except Exception:
            self._logger.exception("Failed to read SI7021 sensor")
            return Reading(temperature=-1, humidity=-1)
        else:
            return Reading(temperature=round(temperature, 1), humidity=round(humidity, 1))
