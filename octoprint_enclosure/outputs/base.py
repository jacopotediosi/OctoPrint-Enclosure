from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.core import BaseConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend

_ConfigT = TypeVar("_ConfigT", bound=BaseConfig)


class OutputError(Exception):
    """Raised when an output can't be used, with the reason as message."""


class Output(ABC, Generic[_ConfigT]):
    """An output, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the output."""

    config: _ConfigT
    """The configuration of the output."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _i2c: I2cBackend
    """The I2C backend."""

    _logger: logging.Logger

    def __init__(self, config: _ConfigT, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        """Set up the output.

        Args:
            config (_ConfigT): The configuration of the output.
            gpio (GpioBackend): The GPIO backend.
            i2c (I2cBackend): The I2C backend.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self._gpio = gpio
        self._i2c = i2c
        self._logger = logger

    @property
    def gpio_pins(self) -> frozenset[int]:
        """The GPIO pins the output drives, empty for an output that drives none."""
        return frozenset()

    def setup(self) -> None:
        """Set up the hardware of the output.

        Raises:
            Exception: If the hardware can't be set up.

        """

    def release(self) -> None:
        """Release the hardware of the output, before its GPIO pins are cleaned up.

        Raises:
            Exception: If the hardware can't be released.

        """

    @abstractmethod
    def turn_off(self) -> None:
        """Turn the output off.

        Raises:
            Exception: If the output can't be written.

        """

    @abstractmethod
    def run_enc_command(self, command: str) -> str | None:
        """Apply an ENC command to the output.

        Args:
            command (str): The G-code line of the ENC command.

        Returns:
            str | None: The reply to write in the terminal, or None if the output has no ENC command.

        Raises:
            Exception: If the command can't be applied.

        """
