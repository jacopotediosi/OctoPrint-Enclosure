from __future__ import annotations

from dataclasses import dataclass

from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.utils import parse_hex

from .base import Reading, Sensor

BUS = 1

TEMPERATURE_REGISTER = 0x00
TEMPERATURE_BYTES = 2
TEMPERATURE_UNUSED_BITS = 4


@dataclass(frozen=True)
class Tmp102Config:
    """The configuration of a TMP102 sensor."""

    temp_sensor_address: int
    """The I2C address of the sensor."""

    def __post_init__(self) -> None:
        """Check the address.

        Raises:
            ValueError: If the address is not one a TMP102 can have.

        """
        if not 0x48 <= self.temp_sensor_address <= 0x4B:
            msg = f"The TMP102 address must be between 0x48 and 0x4B, not {self.temp_sensor_address:#x}"
            raise ValueError(msg)


class Tmp102Sensor(Sensor[Tmp102Config]):
    """A TMP102 temperature sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Tmp102Config:
        return Tmp102Config(temp_sensor_address=parse_hex(settings["temp_sensor_address"]))

    @override
    def read(self) -> Reading:
        address = self.config.temp_sensor_address
        with SMBus(BUS) as bus:
            # Receive the temperature
            temperature_bytes = bus.read_i2c_block_data(address, TEMPERATURE_REGISTER, TEMPERATURE_BYTES)

        raw_temperature = int.from_bytes(temperature_bytes, "big", signed=True) >> TEMPERATURE_UNUSED_BITS

        # Formula from the datasheet
        temperature = raw_temperature / 16

        return Reading(temperature=round(temperature, 1))
