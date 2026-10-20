from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.inputs import Edge

from .base import Trigger


@dataclass(frozen=True)
class GpioInputTriggerConfig(BaseConfig):
    """The configuration of an automation trigger on the edges of a GPIO input."""

    input: int
    """The id of the GPIO input."""

    edge: Edge
    """The edge of the input that starts the automation."""


class GpioInputTrigger(Trigger[GpioInputTriggerConfig]):
    """An automation trigger on an edge of a GPIO input."""

    config_class = GpioInputTriggerConfig

    def matches_level(self, level: int) -> bool:
        """Check whether a level of the input matches the edge of the trigger.

        Args:
            level (int): The level of the input, 1 if high or 0 if low.

        Returns:
            bool: Whether the level matches the edge of the trigger.

        """
        return level == self.config.edge.level
