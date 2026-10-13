from __future__ import annotations

from dataclasses import dataclass

import spidev
from typing_extensions import override

from octoprint_enclosure.utils import parse_hex

from .base import Reading, Sensor

SPI_BUS = 0
SPI_MAX_SPEED_HZ = 5_000_000  # The maximum of the MAX31855
SPI_MODE = 0

RESPONSE_BYTES = 4
RESPONSE_TEMPERATURE_SHIFT = 18
RESPONSE_FAULTS = {
    0b100: "short circuit to VCC",
    0b010: "short circuit to GND",
    0b001: "open circuit",
}


@dataclass(frozen=True)
class Max31855Config:
    """The configuration of a MAX31855 sensor."""

    temp_sensor_address: int
    """The SPI chip select of the sensor, 0 for CE0 or 1 for CE1."""

    def __post_init__(self) -> None:
        """Check the chip select.

        Raises:
            ValueError: If the chip select is not CE0 or CE1.

        """
        if not 0 <= self.temp_sensor_address <= 1:
            msg = f"The MAX31855 chip select must be 0 or 1, not {self.temp_sensor_address}"
            raise ValueError(msg)


class Max31855Sensor(Sensor[Max31855Config]):
    """A MAX31855 thermocouple sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Max31855Config:
        return Max31855Config(temp_sensor_address=parse_hex(settings["temp_sensor_address"]))

    @override
    def read(self) -> Reading:
        try:
            with spidev.SpiDev(SPI_BUS, self.config.temp_sensor_address) as spi:
                spi.max_speed_hz = SPI_MAX_SPEED_HZ
                spi.mode = SPI_MODE

                # Receive the data
                response = int.from_bytes(spi.readbytes(RESPONSE_BYTES), "big", signed=True)

            # Check for faults
            faults = [fault for bit, fault in RESPONSE_FAULTS.items() if response & bit]
            if faults:
                self._logger.error("Failed to read MAX31855 sensor: %s", ", ".join(faults))
                return Reading(temperature=-1)

            # Formula from the datasheet
            temperature = (response >> RESPONSE_TEMPERATURE_SHIFT) / 4
        except Exception:
            self._logger.exception("Failed to read MAX31855 sensor")
            return Reading(temperature=-1)
        else:
            return Reading(temperature=round(temperature, 1))
