from __future__ import annotations

from dataclasses import dataclass

from smbus2 import SMBus
from typing_extensions import override

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.utils import clamp, get_gcode_param, to_int

from .base import Output


@dataclass(frozen=True)
class RegularConfig(BaseConfig):
    """The configuration of a regular output."""

    active_low: bool
    """Whether the output is on when it is low."""

    gpio_i2c_enabled: bool
    """Whether the output is driven by a device on the I2C bus, instead of a GPIO pin."""

    gpio_pin: int
    """The GPIO pin of the output, when it isn't driven through I2C."""

    gpio_i2c_bus: int
    """The number of the I2C bus."""

    gpio_i2c_address: int
    """The I2C address of the device."""

    gpio_i2c_register: int
    """The I2C register written to set the output high or low."""

    gpio_i2c_register_status: int
    """The I2C register read to know whether the output is high."""

    gpio_i2c_data_on: int
    """The value of the I2C registers when the output is high."""

    gpio_i2c_data_off: int
    """The value written via I2C to set the output low."""


class RegularOutput(Output[RegularConfig]):
    """An output that is either on or off, on a GPIO pin or driven by a device on the I2C bus."""

    config_class = RegularConfig

    def setup(self) -> None:
        """Set up the output.

        Raises:
            Exception: If the output can't be set up.

        """
        config = self.config

        if config.gpio_i2c_enabled:
            return

        initial_value = self._gpio.HIGH if config.active_low else self._gpio.LOW
        self._logger.debug("Setting GPIO pin %s as OUTPUT with initial value: %s", config.gpio_pin, initial_value)
        self._gpio.setup(config.gpio_pin, self._gpio.OUT, initial=initial_value)

    def is_on(self) -> bool:
        """Read whether the output is on.

        Returns:
            bool: Whether the output is on.

        Raises:
            Exception: If the output can't be read.

        """
        config = self.config

        if config.gpio_i2c_enabled:
            with SMBus(config.gpio_i2c_bus) as bus:
                data = bus.read_i2c_block_data(config.gpio_i2c_address, config.gpio_i2c_register_status, 1)
            self._logger.debug("Read %s from register %s", data, config.gpio_i2c_register_status)
            high = data[0] == config.gpio_i2c_data_on
        else:
            high = bool(self._gpio.input(config.gpio_pin))

        return high != config.active_low

    def turn_on(self) -> None:
        """Turn the output on.

        Raises:
            Exception: If the output can't be written.

        """
        self._switch(on=True)

    def turn_off(self) -> None:
        """Turn the output off.

        Raises:
            Exception: If the output can't be written.

        """
        self._switch(on=False)

    def toggle(self) -> bool:
        """Turn the output off if it is on, and on if it is off.

        Returns:
            bool: Whether the output is now on.

        Raises:
            Exception: If the output can't be read or written.

        """
        on = not self.is_on()
        self._switch(on=on)
        return on

    def _switch(self, *, on: bool) -> None:
        config = self.config
        high = on != config.active_low

        if config.gpio_i2c_enabled:
            data = config.gpio_i2c_data_on if high else config.gpio_i2c_data_off
            with SMBus(config.gpio_i2c_bus) as bus:
                bus.write_i2c_block_data(config.gpio_i2c_address, config.gpio_i2c_register, [data])
            self._logger.debug(
                "Writing on GPIO (i2c): %s/%s value %s",
                config.gpio_i2c_address,
                config.gpio_i2c_register,
                high,
            )
        else:
            self._gpio.output(config.gpio_pin, high)
            self._logger.debug("Writing on GPIO: %s value %s", config.gpio_pin, high)

    @override
    def run_enc_command(self, command: str) -> str:
        index_id = to_int(get_gcode_param(command, "O"))
        on = clamp(to_int(get_gcode_param(command, "S")), 0, 1) == 1

        if on:
            self.turn_on()
        else:
            self.turn_off()

        return f"Setting REGULAR output {index_id} to value {on}"
