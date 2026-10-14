from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass

from smbus2 import SMBus, i2c_msg
from typing_extensions import override

from octoprint_enclosure.utils import crc16_modbus

from .base import Reading, Sensor, SensorError

BUS = 1
ADDRESS = 0x5C

WAKE_UP_ATTEMPTS = 3

READ_FUNCTION_CODE = 0x03
READ_DELAY_MS = 1
FIRST_REGISTER = 0x00
REGISTER_COUNT = 4

# Read response: the function code, the register count, the registers, then a little endian CRC16
READ_RESPONSE_BYTES = 1 + 1 + REGISTER_COUNT + 2


@dataclass(frozen=True)
class Am2320Config:
    """The configuration of an AM2320 sensor."""


class Am2320Sensor(Sensor[Am2320Config]):
    """An AM2320 temperature and humidity sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Am2320Config:
        return Am2320Config()

    @override
    def read(self) -> Reading:
        with SMBus(BUS) as bus:
            # Wake up: the sleeping sensor doesn't acknowledge these writes
            for _ in range(WAKE_UP_ATTEMPTS):
                with contextlib.suppress(OSError):
                    bus.write_byte(ADDRESS, 0x00)

            # Read the registers
            bus.write_i2c_block_data(ADDRESS, READ_FUNCTION_CODE, (FIRST_REGISTER, REGISTER_COUNT))
            time.sleep(READ_DELAY_MS / 1000)
            read_response_msg = i2c_msg.read(ADDRESS, READ_RESPONSE_BYTES)
            bus.i2c_rdwr(read_response_msg)

        # Parse response
        read_response = bytes(read_response_msg)
        function_code, register_count = read_response[0], read_response[1]
        registers, crc = read_response[2:-2], read_response[-2:]

        # Check response correctness
        header_ok = (function_code, register_count) == (READ_FUNCTION_CODE, REGISTER_COUNT)
        crc_ok = int.from_bytes(crc, "little") == crc16_modbus(read_response[:-2])
        if not header_ok or not crc_ok:
            msg = f"Invalid response: {read_response.hex()}"
            raise SensorError(msg)

        # Registers are: humidity high byte, humidity low byte, temperature high byte, temperature low byte
        raw_humidity = int.from_bytes(registers[:2], "big")
        raw_temperature = int.from_bytes(registers[2:], "big")

        # Formulas from the datasheet: tenths of %RH and of °C, with a sign bit for the temperature
        humidity = raw_humidity / 10
        temperature = (raw_temperature & 0x7FFF) / 10
        if raw_temperature & 0x8000:
            temperature = -temperature

        return Reading(temperature=round(temperature, 1), humidity=round(humidity, 1))
