from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.core import BaseConfig

_ConfigT = TypeVar("_ConfigT", bound="BaseConfig")


@dataclass(frozen=True)
class Reading:
    """A reading of a temperature sensor."""

    temperature: float | None = None
    """The temperature, in Celsius."""

    humidity: float | None = None
    """The relative humidity, in percent."""

    airquality: float | None = None
    """The air quality index."""


class SensorError(Exception):
    """Raised when a sensor can't be read, with the reason as message."""


class Sensor(ABC, Generic[_ConfigT]):
    """A temperature sensor, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the input."""

    config: _ConfigT
    """The configuration of the sensor."""

    _logger: logging.Logger

    def __init__(self, logger: logging.Logger, config: _ConfigT) -> None:
        """Set up the sensor.

        Args:
            logger (logging.Logger): The logger to write to.
            config (_ConfigT): The configuration of the sensor.

        """
        self._logger = logger
        self.config = config

    @abstractmethod
    def read(self) -> Reading:
        """Read the sensor.

        Returns:
            Reading: The values read.

        Raises:
            Exception: If the sensor can't be read.

        """
