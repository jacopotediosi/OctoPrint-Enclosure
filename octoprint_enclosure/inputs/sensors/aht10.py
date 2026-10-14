from __future__ import annotations

from dataclasses import dataclass

from smbus2 import SMBus, i2c_msg
from typing_extensions import override

from octoprint_enclosure.utils import parse_hex

from .base import Reading, Sensor

INITIALIZE_COMMAND = 0xE1
INITIALIZE_PARAMETERS = (0x08, 0x00)  # Bit 3 enables the calibration

MEASURE_COMMAND = 0xAC
MEASURE_PARAMETERS = (0x33, 0x00)

# Measure response: the status byte, then 20 bits of humidity and 20 bits of temperature
MEASURE_RESPONSE_HUM_TEMP_BITS = 20
MEASURE_RESPONSE_BYTES = 1 + 2 * MEASURE_RESPONSE_HUM_TEMP_BITS // 8


@dataclass(frozen=True)
class Aht10Config:
    """The configuration of an AHT10 sensor."""

    temp_sensor_address: int
    """The I2C address of the sensor."""

    temp_sensor_i2cbus: int
    """The number of the I2C bus."""


class Aht10Sensor(Sensor[Aht10Config]):
    """An AHT10 temperature and humidity sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Aht10Config:
        return Aht10Config(
            temp_sensor_address=parse_hex(settings["temp_sensor_address"]),
            temp_sensor_i2cbus=int(str(settings["temp_sensor_i2cbus"])),
        )

    @override
    def read(self) -> Reading:
        address = self.config.temp_sensor_address
        with SMBus(self.config.temp_sensor_i2cbus) as bus:
            # Init and receive status
            bus.write_i2c_block_data(address, INITIALIZE_COMMAND, INITIALIZE_PARAMETERS)
            bus.read_byte(address)

            # Measure and receive data
            bus.write_i2c_block_data(address, MEASURE_COMMAND, MEASURE_PARAMETERS)
            measure_response_msg = i2c_msg.read(address, MEASURE_RESPONSE_BYTES)
            bus.i2c_rdwr(measure_response_msg)

        measure_response_bytes = bytes(measure_response_msg)
        _status, measurement = measure_response_bytes[0], measure_response_bytes[1:]

        raw_hum_temp = int.from_bytes(measurement, "big")
        raw_humidity, raw_temperature = divmod(raw_hum_temp, 2**MEASURE_RESPONSE_HUM_TEMP_BITS)

        # Formulas from the datasheet
        humidity = int(raw_humidity / 2**MEASURE_RESPONSE_HUM_TEMP_BITS * 100)
        temperature = raw_temperature / 2**MEASURE_RESPONSE_HUM_TEMP_BITS * 200 - 50

        return Reading(temperature=round(temperature, 1), humidity=humidity)
