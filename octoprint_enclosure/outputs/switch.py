from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Output


@dataclass(frozen=True)
class SwitchConfig(BaseConfig):
    """The configuration of an output with a switch, on a GPIO pin or driven by a device on the I2C bus."""

    active_low: bool
    """Whether the output switch is on when it is low."""

    gpio_i2c_enabled: bool
    """Whether the output switch is driven by a device on the I2C bus, instead of a GPIO pin."""

    gpio_pin: int
    """The GPIO pin of the output switch, when it isn't driven through I2C."""

    gpio_i2c_bus: int
    """The number of the I2C bus."""

    gpio_i2c_address: int
    """The I2C address of the device."""

    gpio_i2c_register: int
    """The I2C register written to set the output switch high or low."""

    gpio_i2c_register_status: int
    """The I2C register read to know whether the output switch is high."""

    gpio_i2c_data_on: int
    """The value of the I2C registers when the output switch is high."""

    gpio_i2c_data_off: int
    """The value written via I2C to set the output switch low."""


_ConfigT = TypeVar("_ConfigT", bound=SwitchConfig)


class SwitchOutput(Output[_ConfigT]):
    """An output with a switch that is either on or off, on a GPIO pin or driven by a device on the I2C bus."""

    @property
    @override
    def gpio_pins(self) -> frozenset[int]:
        if self.config.gpio_i2c_enabled:
            return frozenset()
        return frozenset({self.config.gpio_pin})

    def setup_pin(self) -> None:
        """Set up the pin of the output switch.

        An output switch driven through I2C has no pin, so nothing is set up.

        Raises:
            Exception: If the pin can't be set up.

        """
        config = self.config

        if config.gpio_i2c_enabled:
            return

        initial_value = self._gpio.HIGH if config.active_low else self._gpio.LOW
        self._logger.debug("Setting GPIO pin %s as OUTPUT with initial value: %s", config.gpio_pin, initial_value)
        self._gpio.setup(config.gpio_pin, self._gpio.OUT, initial=initial_value)

    def is_on(self) -> bool:
        """Read whether the output switch is on.

        Returns:
            bool: Whether the output switch is on.

        Raises:
            Exception: If the output switch can't be read.

        """
        config = self.config

        if config.gpio_i2c_enabled:
            with self._i2c.SMBus(config.gpio_i2c_bus) as bus:
                data = bus.read_i2c_block_data(config.gpio_i2c_address, config.gpio_i2c_register_status, 1)
            self._logger.debug("Read %s from register %s", data, config.gpio_i2c_register_status)
            high = data[0] == config.gpio_i2c_data_on
        else:
            high = bool(self._gpio.input(config.gpio_pin))

        return high != config.active_low

    def _switch(self, *, on: bool) -> None:
        config = self.config
        high = on != config.active_low

        if config.gpio_i2c_enabled:
            data = config.gpio_i2c_data_on if high else config.gpio_i2c_data_off
            with self._i2c.SMBus(config.gpio_i2c_bus) as bus:
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
