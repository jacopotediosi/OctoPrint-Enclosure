from __future__ import annotations

from dataclasses import dataclass

from smbus2 import SMBus
from typing_extensions import override

from .base import I2cSensorConfig, Reading, Sensor

TEMPERATURE_REGISTER = 0x00
TEMPERATURE_BYTES = 2
TEMPERATURE_UNUSED_BITS = 4


@dataclass(frozen=True)
class Tmp102Config(I2cSensorConfig):
    """The configuration of a TMP102 sensor."""


class Tmp102Sensor(Sensor[Tmp102Config]):
    """A TMP102 temperature sensor."""

    config_class = Tmp102Config

    @override
    def read(self) -> Reading:
        address = self.config.temp_sensor_address
        with SMBus(self.config.temp_sensor_i2cbus) as bus:
            # Receive the temperature
            temperature_bytes = bus.read_i2c_block_data(address, TEMPERATURE_REGISTER, TEMPERATURE_BYTES)

        raw_temperature = int.from_bytes(temperature_bytes, "big", signed=True) >> TEMPERATURE_UNUSED_BITS

        # Formula from the datasheet
        temperature = raw_temperature / 16

        return Reading(temperature=round(temperature, 1))
