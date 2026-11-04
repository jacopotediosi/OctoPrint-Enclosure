from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.core import REQUIRED

from .config import OutputConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend


@dataclass(frozen=True)
class SwitchConfig(OutputConfig):
    """The configuration of an output with a switch, on a GPIO pin or driven by a device on the I2C bus."""

    active_low: bool = REQUIRED
    """Whether the output switch is on when it is low."""

    gpio_i2c_enabled: bool = REQUIRED
    """Whether the output switch is driven by a device on the I2C bus, instead of a GPIO pin."""

    gpio_pin: int = REQUIRED
    """The GPIO pin of the output switch, when it isn't driven through I2C."""

    gpio_i2c_bus: int = REQUIRED
    """The number of the I2C bus."""

    gpio_i2c_address: int = REQUIRED
    """The I2C address of the device."""

    gpio_i2c_register: int = REQUIRED
    """The I2C register written to set the output switch high or low."""

    gpio_i2c_register_status: int = REQUIRED
    """The I2C register read to know whether the output switch is high."""

    gpio_i2c_data_on: int = REQUIRED
    """The value of the I2C registers when the output switch is high."""

    gpio_i2c_data_off: int = REQUIRED
    """The value written via I2C to set the output switch low."""


class Switch:
    """A switch that is either on or off, on a GPIO pin or driven by a device on the I2C bus."""

    _config: SwitchConfig
    """The configuration of the output with the switch."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _i2c: I2cBackend
    """The I2C backend."""

    _logger: logging.Logger

    def __init__(self, config: SwitchConfig, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        """Set up the switch.

        Args:
            config (SwitchConfig): The configuration of the output with the switch.
            gpio (GpioBackend): The GPIO backend.
            i2c (I2cBackend): The I2C backend.
            logger (logging.Logger): The logger to write to.

        """
        self._config = config
        self._gpio = gpio
        self._i2c = i2c
        self._logger = logger

    @property
    def gpio_pins(self) -> frozenset[int]:
        """The GPIO pin of the switch, empty for a switch driven through I2C."""
        if self._config.gpio_i2c_enabled:
            return frozenset()
        return frozenset({self._config.gpio_pin})

    def setup(self) -> None:
        """Set up the pin of the switch.

        A switch driven through I2C has no pin, so nothing is set up.

        Raises:
            Exception: If the pin can't be set up.

        """
        config = self._config

        if config.gpio_i2c_enabled:
            return

        initial_value = self._gpio.HIGH if config.active_low else self._gpio.LOW
        self._logger.debug("Setting GPIO pin %s as OUTPUT with initial value: %s", config.gpio_pin, initial_value)
        self._gpio.setup(config.gpio_pin, self._gpio.OUT, initial=initial_value)

    def is_on(self) -> bool:
        """Read whether the switch is on.

        Returns:
            bool: Whether the switch is on.

        Raises:
            Exception: If the switch can't be read.

        """
        config = self._config

        if config.gpio_i2c_enabled:
            with self._i2c.SMBus(config.gpio_i2c_bus) as bus:
                data = bus.read_i2c_block_data(config.gpio_i2c_address, config.gpio_i2c_register_status, 1)
            self._logger.debug("Read %s from register %s", data, config.gpio_i2c_register_status)
            high = data[0] == config.gpio_i2c_data_on
        else:
            high = bool(self._gpio.input(config.gpio_pin))

        return high != config.active_low

    def set(self, *, on: bool) -> None:
        """Turn the switch on or off.

        Args:
            on (bool): Whether to turn the switch on or off.

        Raises:
            Exception: If the switch can't be written.

        """
        config = self._config
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
