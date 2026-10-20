from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.inputs.pull_resistor import PullResistor

if TYPE_CHECKING:
    import logging
    from types import ModuleType


class GpioInputError(Exception):
    """Raised when a GPIO input can't be used, with the reason as message."""


@dataclass(frozen=True)
class GpioConfig(BaseConfig):
    """The configuration of a GPIO input."""

    gpio_pin: int
    """The GPIO pin of the input."""

    input_pull_resistor: PullResistor
    """The pull resistor of the pin."""


class GpioInput:
    """An input that reads the level of a GPIO pin."""

    config_class = GpioConfig
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the input."""

    config: GpioConfig
    """The configuration of the input."""

    _gpio: ModuleType
    """The GPIO backend."""

    _logger: logging.Logger

    def __init__(self, config: GpioConfig, gpio: ModuleType, logger: logging.Logger) -> None:
        """Set up the input.

        Args:
            config (GpioConfig): The configuration of the input.
            gpio (ModuleType): The GPIO backend.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self._gpio = gpio
        self._logger = logger

    def setup_pin(self) -> None:
        """Set up the pin of the input.

        Raises:
            Exception: If the pin can't be set up.

        """
        config = self.config

        pull_resistor = self._gpio.PUD_UP if config.input_pull_resistor is PullResistor.UP else self._gpio.PUD_DOWN
        self._logger.debug("Setting GPIO pin %s as INPUT with pull resistor: %s", config.gpio_pin, pull_resistor)
        self._gpio.setup(config.gpio_pin, self._gpio.IN, pull_resistor)

    def read_pin_level(self) -> int:
        """Read the level of the pin of the input.

        Returns:
            int: The level of the pin, 1 if high or 0 if low.

        Raises:
            Exception: If the pin can't be read.

        """
        return self._gpio.input(self.config.gpio_pin)
