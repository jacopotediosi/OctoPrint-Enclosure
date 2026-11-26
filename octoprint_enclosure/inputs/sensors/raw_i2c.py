from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.config import HexInt, config_field
from octoprint_enclosure.utils import N_, MeasurementType

from .base import Reading, Sensor, SensorError, SensorInputConfig


@dataclass(frozen=True)
class RawI2cConfig(SensorInputConfig):
    """The configuration of a device sending its readings over I2C as raw floats."""

    type_help = N_(
        '<span class="label label-important">Attention</span> I2C needs to be enabled: run '
        "<code>sudo raspi-config</code> and enable I2C in the interface options. When the register is read, the device "
        "must return two 4-byte little-endian floats: the temperature in °C then the humidity in %% for Raw I2C "
        "Temperature, the humidity then the temperature for Raw I2C Humidity. The second float can be "
        "<code>NaN</code>.",
    )

    temp_i2c_bus: int = config_field(
        default=1,
        label=N_("I2C Bus"),
        help_text=N_(
            "1 is the bus of GPIO 2 and 3. For a device on another bus, for example one made on other pins with "
            "<code>dtoverlay=i2c-gpio</code>, use its number: <code>i2cdetect -l</code> lists the buses.",
        ),
        min_value=0,
    )
    """The number of the I2C bus."""

    temp_i2c_address: HexInt = config_field(
        label=N_("I2C Address"),
        help_text=N_(
            "Address of the device, in hexadecimal. Find it by running <code>i2cdetect -y 1</code> (from the "
            "<code>i2c-tools</code> package) on your Raspberry Pi.",
        ),
        min_value=0,
        max_value=127,
    )
    """The I2C address of the device."""

    temp_i2c_register: HexInt = config_field(
        label=N_("I2C Register"),
        help_text=N_("Register to read, in hexadecimal."),
        min_value=0,
        max_value=255,
    )
    """The register to read the floats from."""


class _RawI2cSensor(Sensor[RawI2cConfig]):
    """A device sending two readings over I2C as raw floats."""

    config_class = RawI2cConfig
    measurement_types = frozenset({MeasurementType.TEMPERATURE, MeasurementType.HUMIDITY})

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
