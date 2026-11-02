from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.inputs.config import InputConfig, PullResistor

if TYPE_CHECKING:
    import logging


@dataclass(frozen=True)
class SensorInputConfig(InputConfig):
    """The configuration shared by all the inputs with a temperature sensor."""

    temp_sensor_type: str = ""
    """The type of the sensor."""

    show_graph_temp: bool = False
    """Whether the temperature is shown in the temperature graph."""

    show_graph_humidity: bool = False
    """Whether the humidity is shown in the temperature graph."""

    gpio_pin: int = 0
    """The GPIO pin of the sensor, for the sensors that use one."""

    input_pull_resistor: PullResistor = PullResistor.OFF
    """The pull resistor of the pin of the sensor."""


_ConfigT = TypeVar("_ConfigT", bound=SensorInputConfig)


@dataclass(frozen=True)
class Reading:
    """A reading of a temperature sensor."""

    temperature: float | None = None
    """The temperature, in Celsius."""

    humidity: float | None = None
    """The relative humidity, in percent."""

    airquality: float | None = None
    """The air quality index."""

    def __post_init__(self) -> None:
        """Round the values to one decimal."""
        for name in ("temperature", "humidity", "airquality"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, round(float(value), 1))


class SensorError(Exception):
    """Raised when a sensor can't be read, with the reason as message."""


class Sensor(ABC, Generic[_ConfigT]):
    """A temperature sensor, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the input."""

    config: _ConfigT
    """The configuration of the sensor."""

    _logger: logging.Logger

    def __init__(self, config: _ConfigT, logger: logging.Logger) -> None:
        """Set up the sensor.

        Args:
            config (_ConfigT): The configuration of the sensor.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self._logger = logger

    @abstractmethod
    def read(self) -> Reading:
        """Read the sensor.

        Returns:
            Reading: The values read.

        Raises:
            Exception: If the sensor can't be read.

        """
