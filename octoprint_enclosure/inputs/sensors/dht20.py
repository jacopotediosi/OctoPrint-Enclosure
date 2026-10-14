from __future__ import annotations

from dataclasses import dataclass

from smbus2 import SMBus, i2c_msg
from typing_extensions import override

from octoprint_enclosure.utils import parse_hex

from .base import Reading, Sensor

STATUS_COMMAND = 0x71

MEASURE_COMMAND = 0xAC
MEASURE_PARAMETERS = (0x33, 0x00)

# Measure response: the status byte, then 20 bits of humidity and 20 bits of temperature
MEASURE_RESPONSE_HUM_TEMP_BITS = 20
MEASURE_RESPONSE_BYTES = 1 + 2 * MEASURE_RESPONSE_HUM_TEMP_BITS // 8


@dataclass(frozen=True)
class Dht20Config:
    """The configuration of a DHT20 sensor."""

    temp_sensor_address: int
    """The I2C address of the sensor."""

    temp_sensor_i2cbus: int
    """The number of the I2C bus."""


class Dht20Sensor(Sensor[Dht20Config]):
    """A DHT20 temperature and humidity sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Dht20Config:
        return Dht20Config(
            temp_sensor_address=parse_hex(settings["temp_sensor_address"]),
            temp_sensor_i2cbus=int(str(settings["temp_sensor_i2cbus"])),
        )

    @override
    def read(self) -> Reading:
        address = self.config.temp_sensor_address
        with SMBus(self.config.temp_sensor_i2cbus) as bus:
            # Receive status
            bus.read_i2c_block_data(address, STATUS_COMMAND, 1)

            # Measure and receive data
            bus.write_i2c_block_data(address, MEASURE_COMMAND, MEASURE_PARAMETERS)
            measure_response_msg = i2c_msg.read(address, MEASURE_RESPONSE_BYTES)
            bus.i2c_rdwr(measure_response_msg)

        measure_response_bytes = bytes(measure_response_msg)
        _status, measurement = measure_response_bytes[0], measure_response_bytes[1:]

        raw_hum_temp = int.from_bytes(measurement, "big")
        raw_humidity, raw_temperature = divmod(raw_hum_temp, 2**MEASURE_RESPONSE_HUM_TEMP_BITS)

        # Formulas from the datasheet
        humidity = raw_humidity / 2**MEASURE_RESPONSE_HUM_TEMP_BITS * 100
        temperature = raw_temperature / 2**MEASURE_RESPONSE_HUM_TEMP_BITS * 200 - 50

        return Reading(temperature=round(temperature, 1), humidity=round(humidity, 1))
