from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.inputs.config import InputConfig, PullResistor
from octoprint_enclosure.settings import REQUIRED

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend


class GpioInputError(Exception):
    """Raised when a GPIO input can't be used, with the reason as message."""


@dataclass(frozen=True)
class GpioConfig(InputConfig):
    """The configuration of a GPIO input."""

    gpio_pin: int = REQUIRED
    """The GPIO pin of the input."""

    input_pull_resistor: PullResistor = REQUIRED
    """The pull resistor of the pin."""


class GpioInput:
    """An input that reads the level of a GPIO pin."""

    config_class = GpioConfig
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the input."""

    config: GpioConfig
    """The configuration of the input."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _logger: logging.Logger

    _unreadable: bool
    """Whether the pin couldn't be read the last time."""

    _unreadable_lock: threading.Lock
    """Held by every access to whether the pin couldn't be read the last time."""

    def __init__(self, config: GpioConfig, gpio: GpioBackend, logger: logging.Logger) -> None:
        """Set up the input.

        Args:
            config (GpioConfig): The configuration of the input.
            gpio (GpioBackend): The GPIO backend.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self._gpio = gpio
        self._logger = logger
        self._unreadable = False
        self._unreadable_lock = threading.Lock()

    def setup_pin(self) -> None:
        """Set up the pin of the input.

        Raises:
            Exception: If the pin can't be set up.

        """
        config = self.config

        pull_resistors = {
            PullResistor.UP: self._gpio.PUD_UP,
            PullResistor.DOWN: self._gpio.PUD_DOWN,
            PullResistor.OFF: self._gpio.PUD_OFF,
        }
        pull_resistor = pull_resistors[config.input_pull_resistor]
        self._logger.debug("Setting GPIO pin %s as INPUT with pull resistor: %s", config.gpio_pin, pull_resistor)
        self._gpio.setup(config.gpio_pin, self._gpio.IN, pull_resistor)

    def read_pin_level(self) -> int | None:
        """Read the level of the pin of the input.

        Returns:
            int | None: The level of the pin, 1 if high or 0 if low, or None if the pin can't be read.

        """
        # Read the pin
        try:
            level = self._gpio.input(self.config.gpio_pin)
        except Exception:
            with self._unreadable_lock:
                stopped_working = not self._unreadable
                self._unreadable = True
            if stopped_working:
                self._logger.exception("The pin of input %s can't be read", self.config.index_id)
            return None

        # Log the pin that can be read again
        with self._unreadable_lock:
            works_again = self._unreadable
            self._unreadable = False
        if works_again:
            self._logger.warning("The pin of input %s can be read again", self.config.index_id)

        return level

    def is_active(self) -> bool | None:
        """Check whether the input is active.

        Returns:
            bool | None: Whether the input is active: with a pull-up resistor when its pin is low, otherwise when its
                pin is high. None if the pin can't be read.

        """
        level = self.read_pin_level()
        if level is None:
            return None

        active_level = 0 if self.config.input_pull_resistor is PullResistor.UP else 1
        return level == active_level
