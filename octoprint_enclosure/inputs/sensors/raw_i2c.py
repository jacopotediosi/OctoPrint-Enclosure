from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Reading, Sensor, SensorError


@dataclass(frozen=True)
class RawI2cConfig(BaseConfig):
    """The configuration of a device sending its readings over I2C as raw floats."""

    temp_i2c_bus: int
    """The number of the I2C bus."""

    temp_i2c_address: int
    """The I2C address of the device."""

    temp_i2c_register: int
    """The register to read the floats from."""


class _RawI2cSensor(Sensor[RawI2cConfig]):
    """A device sending two readings over I2C as raw floats."""

    config_class = RawI2cConfig

    def _read_floats(self) -> tuple[float | None, float | None]:
        with SMBus(self.config.temp_i2c_bus) as bus:
            data = bus.read_i2c_block_data(self.config.temp_i2c_address, self.config.temp_i2c_register, 8)

        fval1 = struct.unpack("f", bytearray(data[0:4]))[0]
        if math.isnan(fval1):
            self._logger.debug("The first float is NaN: %s", bytes(data[0:4]).hex())
            fval1 = None

        fval2 = struct.unpack("f", bytearray(data[4:8]))[0]
        if math.isnan(fval2):
            self._logger.debug("The second float is NaN: %s", bytes(data[4:8]).hex())
            fval2 = None

        return (fval1, fval2)


class RawI2cTemperatureSensor(_RawI2cSensor):
    """A device sending the temperature and then the humidity over I2C as raw floats."""

    @override
    def read(self) -> Reading:
        temperature, humidity = self._read_floats()

        if temperature is None:
            msg = "The device sent NaN as the temperature"
            raise SensorError(msg)

        return Reading(temperature=temperature, humidity=humidity)


class RawI2cHumiditySensor(_RawI2cSensor):
    """A device sending the humidity and then the temperature over I2C as raw floats."""

    @override
    def read(self) -> Reading:
        humidity, temperature = self._read_floats()

        if humidity is None:
            msg = "The device sent NaN as the humidity"
            raise SensorError(msg)

        return Reading(temperature=temperature, humidity=humidity)
