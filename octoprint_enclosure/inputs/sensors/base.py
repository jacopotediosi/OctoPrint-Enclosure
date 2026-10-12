from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging


@dataclass(frozen=True)
class Reading:
    """A reading of a temperature sensor."""

    temperature: float
    """The temperature, in Celsius."""

    humidity: float
    """The relative humidity, in percent."""

    airquality: float
    """The air quality index."""


class Sensor(ABC):
    """A temperature sensor."""

    def __init__(self, logger: logging.Logger) -> None:
        """Set up the sensor.

        Args:
            logger (logging.Logger): The logger to write to.

        """
        self._logger = logger

    @abstractmethod
    def read(self) -> Reading:
        """Read the sensor.

        Returns:
            Reading: The values read.

        """
