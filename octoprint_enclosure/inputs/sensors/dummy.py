from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from .base import Reading, Sensor, SensorError

if TYPE_CHECKING:
    import logging

VALUE_MIN = 20.0
VALUE_MAX = 50.0
VALUE_DELTA = 0.5


@dataclass(frozen=True)
class DummyConfig:
    """The configuration of a dummy sensor."""


class DummySensor(Sensor[DummyConfig]):
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

    def __init__(self, logger: logging.Logger, config: DummyConfig) -> None:
        super().__init__(logger, config)
        self.value = round(random.uniform(VALUE_MIN, VALUE_MAX), 1)  # noqa: S311 - not used for security
        self.value_min = VALUE_MIN
        self.value_max = VALUE_MAX
        self.value_delta = VALUE_DELTA
        self.failing = False

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> DummyConfig:
        return DummyConfig()

    @override
    def read(self) -> Reading:
        if self.failing:
            msg = "The dummy sensor is set to fail"
            raise SensorError(msg)

        reading = Reading(temperature=self.value, humidity=self.value, airquality=self.value)

        self.value += self.value_delta
        if self.value >= self.value_max:
            self.value = self.value_max
            self.value_delta = -abs(self.value_delta)
        elif self.value <= self.value_min:
            self.value = self.value_min
            self.value_delta = abs(self.value_delta)

        return reading
