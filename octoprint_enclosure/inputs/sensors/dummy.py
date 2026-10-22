from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.utils import clamp

from .base import Reading, Sensor, SensorError

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

TEMPERATURE_MIN_C = 15.0
TEMPERATURE_MAX_C = 25.0
TEMPERATURE_DELTA_C = 0.5

HUMIDITY_MIN_PERCENT = 40.0
HUMIDITY_MAX_PERCENT = 60.0
HUMIDITY_DELTA_PERCENT = 1.0

PUSHED_DELTA = 5.0
"""How much a value changes at each reading while a heater, a cooler or a dehumidifier pushes it."""


@dataclass(frozen=True)
class DummyConfig(BaseConfig):
    """The configuration of a dummy sensor."""


class DummyValue:
    """A simulated value, that swings between the minimum and the maximum of its surroundings."""

    value: float
    """The value of the last reading."""

    minimum: float
    """The lowest value of the swing."""

    maximum: float
    """The highest value of the swing."""

    delta: float
    """How much the value changes at each reading by itself."""

    def __init__(self, minimum: float, maximum: float, delta: float) -> None:
        """Set up the value, starting at random between the minimum and the maximum.

        Args:
            minimum (float): The lowest value of the swing.
            maximum (float): The highest value of the swing.
            delta (float): How much the value changes at each reading.

        """
        self.value = round(random.uniform(minimum, maximum), 1)  # noqa: S311 - not used for security
        self.minimum = minimum
        self.maximum = maximum
        self.delta = delta

    def advance(self, *, pushed_up: bool = False, pushed_down: bool = False) -> None:
        """Move the value to the next reading.

        Args:
            pushed_up (bool): Whether a device, like a heater, is pushing the value up.
            pushed_down (bool): Whether a device, like a cooler, is pushing the value down.

        """
        # The sign of the delta is the direction: a device sets it, otherwise the value turns back at the limits
        if pushed_up:
            self.delta = abs(self.delta)
        elif pushed_down or self.value >= self.maximum:
            self.delta = -abs(self.delta)
        elif self.value <= self.minimum:
            self.delta = abs(self.delta)

        if pushed_up or pushed_down:
            # A device moves the value faster than it moves by itself, and beyond the limits
            self.value += PUSHED_DELTA if pushed_up else -PUSHED_DELTA
        elif self.minimum <= self.value <= self.maximum:
            # The swing stops at the limits
            self.value = clamp(self.value + self.delta, self.minimum, self.maximum)
        else:
            # A value outside the limits comes back one delta at a time
            self.value += self.delta

        # Keeps the float error of the sums from showing up in the readings
        self.value = round(self.value, 2)


class DummySensor(Sensor[DummyConfig]):
    """A fake sensor for development purposes."""

    config_class = DummyConfig

    temperature: DummyValue
    """The temperature, in Celsius."""

    humidity: DummyValue
    """The relative humidity, in percent."""

    failing: bool
    """Whether reading the sensor must fail."""

    is_heater_on: Callable[[], bool]
    """Tells whether a heater is warming the sensor up."""

    is_cooler_on: Callable[[], bool]
    """Tells whether a cooler is cooling the sensor down."""

    is_dehumidifier_on: Callable[[], bool]
    """Tells whether a dehumidifier is drying the sensor."""

    def __init__(self, config: DummyConfig, logger: logging.Logger) -> None:
        super().__init__(config, logger)
        self.temperature = DummyValue(TEMPERATURE_MIN_C, TEMPERATURE_MAX_C, TEMPERATURE_DELTA_C)
        self.humidity = DummyValue(HUMIDITY_MIN_PERCENT, HUMIDITY_MAX_PERCENT, HUMIDITY_DELTA_PERCENT)
        self.failing = False
        self.is_heater_on = lambda: False
        self.is_cooler_on = lambda: False
        self.is_dehumidifier_on = lambda: False

    @override
    def read(self) -> Reading:
        if self.failing:
            msg = "The dummy sensor is set to fail"
            raise SensorError(msg)

        self.temperature.advance(pushed_up=self.is_heater_on(), pushed_down=self.is_cooler_on())
        self.humidity.advance(pushed_down=self.is_dehumidifier_on())

        return Reading(temperature=self.temperature.value, humidity=self.humidity.value)
