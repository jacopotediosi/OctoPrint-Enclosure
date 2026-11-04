from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from octoprint_enclosure.inputs import Reading


@dataclass(frozen=True)
class AutomationEvent:
    """Something that happened, that the automation triggers are asked about."""


@dataclass(frozen=True)
class GpioEdgeEvent(AutomationEvent):
    """A GPIO input changed level."""

    input_id: int
    """The id of the input."""

    level: int
    """The level of the input after the edge, 1 if high or 0 if low."""


@dataclass(frozen=True)
class ReadingsEvent(AutomationEvent):
    """A sensor has a new reading."""

    readings: Mapping[int, Reading]
    """The latest reading of every sensor, by the id of its input."""

    index_id: int
    """The id of the input of the sensor that has the new reading."""
