from __future__ import annotations

from dataclasses import dataclass

import bme280
from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.utils import parse_hex

from .base import Reading, Sensor

BUS = 1


@dataclass(frozen=True)
class Bme280Config:
    """The configuration of a BME280 sensor."""

    temp_sensor_address: int
    """The I2C address of the sensor."""


class Bme280Sensor(Sensor[Bme280Config]):
    """A BME280 temperature and humidity sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Bme280Config:
        return Bme280Config(temp_sensor_address=parse_hex(settings["temp_sensor_address"]))

    @override
    def read(self) -> Reading:
        try:
            with SMBus(BUS) as bus:
                calibration_params = bme280.load_calibration_params(bus, self.config.temp_sensor_address)
                readings = bme280.sample(bus, self.config.temp_sensor_address, calibration_params)
        except Exception:
            self._logger.exception("Failed to read BME280 sensor")
            return Reading(temperature=-1, humidity=-1)
        else:
            return Reading(temperature=round(readings.temperature, 1), humidity=round(readings.humidity, 1))
