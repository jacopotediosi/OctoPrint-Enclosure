from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, TypeVar

from typing_extensions import override

from octoprint_enclosure.core import REQUIRED, HexInt
from octoprint_enclosure.inputs.config import InputConfig, PullResistor

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend


##########
### All sensors
##########


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


@dataclass(frozen=True)
class SensorInputConfig(InputConfig):
    """The configuration shared by all the inputs with a temperature sensor."""

    temp_sensor_type: str = ""
    """The type of the sensor."""

    show_graph_temp: bool = field(default=False, compare=False)
    """Whether the temperature is shown in the temperature graph."""

    show_graph_humidity: bool = field(default=False, compare=False)
    """Whether the humidity is shown in the temperature graph."""


_ConfigT = TypeVar("_ConfigT", bound=SensorInputConfig)


class Sensor(ABC, Generic[_ConfigT]):
    """A temperature sensor, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the input."""

    config: _ConfigT
    """The configuration of the sensor."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _logger: logging.Logger

    def __init__(self, config: _ConfigT, gpio: GpioBackend, logger: logging.Logger) -> None:
        """Set up the sensor.

        Args:
            config (_ConfigT): The configuration of the sensor.
            gpio (GpioBackend): The GPIO backend.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self._gpio = gpio
        self._logger = logger

    @property
    def gpio_pins(self) -> frozenset[int]:
        """The GPIO pins the sensor sets up."""
        return frozenset()

    def setup(self) -> None:
        """Set up the pins of the sensor.

        Raises:
            Exception: If the pins can't be set up.

        """

    @abstractmethod
    def read(self) -> Reading:
        """Read the sensor.

        Returns:
            Reading: The values read.

        Raises:
            Exception: If the sensor can't be read.

        """


##########
### Sensors on a GPIO pin
##########


@dataclass(frozen=True)
class PinSensorConfig(SensorInputConfig):
    """The configuration shared by the sensors with a data line on a GPIO pin."""

    gpio_pin: int = REQUIRED
    """The GPIO pin of the data line."""

    input_pull_resistor: PullResistor = PullResistor.OFF
    """The internal pull resistor of the data line."""


_PinConfigT = TypeVar("_PinConfigT", bound=PinSensorConfig)


class PinSensor(Sensor[_PinConfigT]):
    """A sensor with a data line on a GPIO pin."""

    @property
    @override
    def gpio_pins(self) -> frozenset[int]:
        if self.config.input_pull_resistor is PullResistor.OFF:
            return frozenset()
        return frozenset({self.config.gpio_pin})

    @override
    def setup(self) -> None:
        config = self.config

        if config.input_pull_resistor is PullResistor.OFF:
            return

        pull_resistors = {PullResistor.UP: self._gpio.PUD_UP, PullResistor.DOWN: self._gpio.PUD_DOWN}
        pull_resistor = pull_resistors[config.input_pull_resistor]
        self._logger.debug("Setting GPIO pin %s as INPUT with pull resistor: %s", config.gpio_pin, pull_resistor)
        self._gpio.setup(config.gpio_pin, self._gpio.IN, pull_up_down=pull_resistor)


##########
### Sensors on the I2C bus
##########


@dataclass(frozen=True)
class I2cSensorConfig(SensorInputConfig):
    """The configuration shared by the sensors on the I2C bus."""

    temp_sensor_address: HexInt = REQUIRED
    """The I2C address of the sensor."""

    temp_sensor_i2cbus: int = 1
    """The number of the I2C bus."""
