from __future__ import annotations

from dataclasses import dataclass

from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.core import BaseConfig, HexInt

from .base import Reading, Sensor

CONFIG_REGISTER = 0x01
CONFIG_CONTINUOUS_CONVERSION = (0x00, 0x00)  # The power-up default

RESOLUTION_REGISTER = 0x08
RESOLUTION_0_0625 = 0x03  # The finest resolution, in °C

# Ambient temperature register: 3 alert bits, then the temperature as a 13-bit two's complement number of 1/16 °C
AMBIENT_TEMPERATURE_REGISTER = 0x05
AMBIENT_TEMPERATURE_BYTES = 2
AMBIENT_TEMPERATURE_BITS = 13


@dataclass(frozen=True)
class Mcp9808Config(BaseConfig):
    """The configuration of an MCP9808 sensor."""

    temp_sensor_address: HexInt
    """The I2C address of the sensor."""

    temp_sensor_i2cbus: int
    """The number of the I2C bus."""


class Mcp9808Sensor(Sensor[Mcp9808Config]):
    """An MCP9808 temperature sensor."""

    config_class = Mcp9808Config

    @override
    def read(self) -> Reading:
        address = self.config.temp_sensor_address
        with SMBus(self.config.temp_sensor_i2cbus) as bus:
            # Configure
            bus.write_i2c_block_data(address, CONFIG_REGISTER, CONFIG_CONTINUOUS_CONVERSION)
            bus.write_byte_data(address, RESOLUTION_REGISTER, RESOLUTION_0_0625)

            # Receive data
            ambient_temperature = bus.read_i2c_block_data(
                address,
                AMBIENT_TEMPERATURE_REGISTER,
                AMBIENT_TEMPERATURE_BYTES,
            )

        raw_temperature = int.from_bytes(ambient_temperature, "big") % 2**AMBIENT_TEMPERATURE_BITS
        if raw_temperature >= 2 ** (AMBIENT_TEMPERATURE_BITS - 1):
            raw_temperature -= 2**AMBIENT_TEMPERATURE_BITS

        # Formula from the datasheet
        temperature = raw_temperature / 16

        return Reading(temperature=round(temperature, 2))
