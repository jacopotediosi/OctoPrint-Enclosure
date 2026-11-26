from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.automations.events import GpioEdgeEvent
from octoprint_enclosure.config import BaseConfig, GpioInputId, config_field
from octoprint_enclosure.inputs import Edge
from octoprint_enclosure.utils import N_

from .base import Trigger

if TYPE_CHECKING:
    from octoprint_enclosure.automations.events import AutomationEvent


@dataclass(frozen=True)
class GpioInputTriggerConfig(BaseConfig):
    """The configuration of an automation trigger on the edges of a GPIO input."""

    input: GpioInputId = config_field(
        label=N_("Input"),
        help_text=N_("GPIO input that triggers the automation. Configured in the Inputs tab."),
    )
    """The id of the GPIO input."""

    edge: Edge = config_field(
        default=Edge.FALL,
        label=N_("Edge"),
        help_text=N_(
            "If your button or sensor connects the pin to ground, Fall is when it does and Rise when it stops. If it "
            "connects it to 3.3V, it is the opposite.",
        ),
    )
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
