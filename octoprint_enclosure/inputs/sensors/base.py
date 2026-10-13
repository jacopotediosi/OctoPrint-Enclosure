from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    import logging

_ConfigT = TypeVar("_ConfigT")


@dataclass(frozen=True)
class Reading:
    """A reading of a temperature sensor."""

    temperature: float | None = None
    """The temperature, in Celsius."""

    humidity: float | None = None
    """The relative humidity, in percent."""

    airquality: float | None = None
    """The air quality index."""


class Sensor(ABC, Generic[_ConfigT]):
    """A temperature sensor, generic over the type of its configuration."""

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

    @classmethod
    @abstractmethod
    def parse_config(cls, settings: dict) -> _ConfigT:
        """Get the configuration of the sensor from the settings of its input.

        Args:
            settings (dict): The settings of the input.

        Returns:
            _ConfigT: The configuration of the sensor.

        """

    @abstractmethod
    def read(self) -> Reading:
        """Read the sensor.

        Returns:
            Reading: The values read.

        """
