from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.automations.events import GpioEdgeEvent
from octoprint_enclosure.inputs import Edge
from octoprint_enclosure.settings import REQUIRED, BaseConfig

from .base import Trigger

if TYPE_CHECKING:
    from octoprint_enclosure.automations.events import AutomationEvent


@dataclass(frozen=True)
class GpioInputTriggerConfig(BaseConfig):
    """The configuration of an automation trigger on the edges of a GPIO input."""

    input: int = REQUIRED
    """The id of the GPIO input."""

    edge: Edge = REQUIRED
    """The edge of the input that starts the automation."""


class GpioInputTrigger(Trigger[GpioInputTriggerConfig]):
    """An automation trigger on an edge of a GPIO input."""

    config_class = GpioInputTriggerConfig

    @override
    def matches(self, event: AutomationEvent) -> bool:
        return (
            isinstance(event, GpioEdgeEvent)
            and event.input_id == self.config.input
            and event.level == self.config.edge.level
        )
