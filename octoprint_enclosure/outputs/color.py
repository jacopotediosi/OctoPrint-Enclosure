from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from typing_extensions import override

from octoprint_enclosure.settings import BaseConfig
from octoprint_enclosure.utils import Rgb

from .base import Output
from .config import OutputConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend

_ConfigT = TypeVar("_ConfigT", bound=OutputConfig)


@dataclass(frozen=True)
class ColorSetpoint(BaseConfig):
    """The setpoint an output that shows a color is turned on to."""

    color: Rgb = Rgb(0, 0, 0)
    """The color, saved as "#rrggbb"."""


class ColorOutput(Output[_ConfigT, ColorSetpoint]):
    """An output that shows a color, like a LED strip."""

    setpoint_class = ColorSetpoint

    _color: Rgb | None
    """The last color set, or None if no color was set yet."""

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
    def color(self) -> Rgb | None:
        """The last color set, or None if no color was set yet."""
        return self._color

    @override
    def _is_on(self) -> bool:
        """Tell whether a color other than black is set."""
        return self._color is not None and self._color != Rgb(0, 0, 0)

    def turn_on(self, setpoint: ColorSetpoint) -> None:
        """Set a color.

        Args:
            setpoint (ColorSetpoint): The color.

        Raises:
            Exception: If the color can't be set.

        """
        self._set_color(*setpoint.color)

    @override
    def turn_off(self) -> None:
        """Turn the LEDs off.

        Raises:
            Exception: If the output can't be written.

        """
        self._set_color(0, 0, 0)

    def _set_color(self, red: int, green: int, blue: int) -> None:
        self._write_color(red, green, blue)
        self._color = Rgb(red, green, blue)

    @abstractmethod
    def _write_color(self, red: int, green: int, blue: int) -> None:
        """Send a color to the hardware, raising an exception if it can't be set."""
