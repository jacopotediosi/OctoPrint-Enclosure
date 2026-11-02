from __future__ import annotations

from dataclasses import dataclass

import bme280
from smbus2 import SMBus
from typing_extensions import override

from .base import I2cSensorConfig, Reading, Sensor


@dataclass(frozen=True)
class Bme280Config(I2cSensorConfig):
    """The configuration of a BME280 sensor."""


class Bme280Sensor(Sensor[Bme280Config]):
    """A BME280 temperature and humidity sensor."""

    config_class = Bme280Config

    @override
    def read(self) -> Reading:
        with SMBus(self.config.temp_sensor_i2cbus) as bus:
            calibration_params = bme280.load_calibration_params(bus, self.config.temp_sensor_address)
            readings = bme280.sample(bus, self.config.temp_sensor_address, calibration_params)

        return Reading(temperature=round(readings.temperature, 1), humidity=round(readings.humidity, 1))
