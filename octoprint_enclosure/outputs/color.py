from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, TypeVar

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Output

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend

_ConfigT = TypeVar("_ConfigT", bound=BaseConfig)


class ColorOutput(Output[_ConfigT]):
    """An output that shows a color, like a LED strip."""

    _color: tuple[int, int, int] | None
    """The last color set, as red, green and blue from 0 to 255, or None if no color was set yet."""

    def __init__(self, config: _ConfigT, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        """Set up the output.

        Args:
            config (_ConfigT): The configuration of the output.
            gpio (GpioBackend): The GPIO backend.
            i2c (I2cBackend): The I2C backend.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, gpio, i2c, logger)
        self._color = None

    @property
    def color(self) -> tuple[int, int, int] | None:
        """The last color set, as red, green and blue from 0 to 255, or None if no color was set yet."""
        return self._color

    def set_color(self, red: int, green: int, blue: int) -> None:
        """Set the color of the output.

        Args:
            red (int): The red component, from 0 to 255.
            green (int): The green component, from 0 to 255.
            blue (int): The blue component, from 0 to 255.

        Raises:
            Exception: If the color can't be set.

        """
        self._write_color(red, green, blue)
        self._color = (red, green, blue)

    @override
    def turn_off(self) -> None:
        """Turn the LEDs off.

        Raises:
            Exception: If the output can't be written.

        """
        self.set_color(0, 0, 0)

    @abstractmethod
    def _write_color(self, red: int, green: int, blue: int) -> None:
        """Send a color to the hardware, raising an exception if it can't be set."""
