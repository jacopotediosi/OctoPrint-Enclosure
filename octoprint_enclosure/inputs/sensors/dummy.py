from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from .base import Reading, Sensor

if TYPE_CHECKING:
    import logging

VALUE_MIN = 30.0
VALUE_MAX = 40.0
VALUE_DELTA = 0.5


class DummySensor(Sensor):
    """A fake sensor for development purposes."""

    def __init__(self, logger: logging.Logger) -> None:
        super().__init__(logger)
        self._value = VALUE_MIN
        self._delta = VALUE_DELTA

    @override
    def read(self) -> Reading:
        self._value += self._delta
        if not VALUE_MIN < self._value < VALUE_MAX:
            self._delta = -self._delta

        return Reading(self._value, self._value, self._value)
