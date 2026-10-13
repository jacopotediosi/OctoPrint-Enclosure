from __future__ import annotations

import random
from typing import TYPE_CHECKING

from typing_extensions import override

from .base import Reading, Sensor

if TYPE_CHECKING:
    import logging

VALUE_MIN = 20.0
VALUE_MAX = 50.0
VALUE_DELTA = 0.5


class DummySensor(Sensor):
    """A fake sensor for development purposes, whose values swing between a minimum and a maximum."""

    value: float
    """The value of the next reading."""

    value_min: float
    """The lowest value the readings swing to."""

    value_max: float
    """The highest value the readings swing to."""

    value_delta: float
    """How much the value changes at each reading."""

    failing: bool
    """Whether reading the sensor must fail."""

    def __init__(self, logger: logging.Logger) -> None:
        super().__init__(logger)
        self.value = round(random.uniform(VALUE_MIN, VALUE_MAX), 1)  # noqa: S311 - not used for security
        self.value_min = VALUE_MIN
        self.value_max = VALUE_MAX
        self.value_delta = VALUE_DELTA
        self.failing = False

    @override
    def read(self) -> Reading:
        if self.failing:
            msg = "The dummy sensor is set to fail"
            raise RuntimeError(msg)

        reading = Reading(self.value, self.value, self.value)

        self.value += self.value_delta
        if self.value >= self.value_max:
            self.value = self.value_max
            self.value_delta = -abs(self.value_delta)
        elif self.value <= self.value_min:
            self.value = self.value_min
            self.value_delta = abs(self.value_delta)

        return reading
