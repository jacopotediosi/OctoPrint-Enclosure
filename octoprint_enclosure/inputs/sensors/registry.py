from __future__ import annotations

from typing import TYPE_CHECKING

from .dummy import DummySensor

if TYPE_CHECKING:
    from .base import Sensor

SENSORS: dict[str, type[Sensor]] = {
    "dummy": DummySensor,
}
"""The supported kinds of temperature sensors, by identifier."""
