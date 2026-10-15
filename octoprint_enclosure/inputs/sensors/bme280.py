from __future__ import annotations

from dataclasses import dataclass

import bme280
from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.core import BaseConfig, HexInt

from .base import Reading, Sensor

BUS = 1


@dataclass(frozen=True)
class Bme280Config(BaseConfig):
    """The configuration of a BME280 sensor."""

    temp_sensor_address: HexInt
    """The I2C address of the sensor."""


class Bme280Sensor(Sensor[Bme280Config]):
    """A BME280 temperature and humidity sensor."""

    config_class = Bme280Config

    @override
    def read(self) -> Reading:
        with SMBus(BUS) as bus:
            calibration_params = bme280.load_calibration_params(bus, self.config.temp_sensor_address)
            readings = bme280.sample(bus, self.config.temp_sensor_address, calibration_params)

        return Reading(temperature=round(readings.temperature, 1), humidity=round(readings.humidity, 1))
