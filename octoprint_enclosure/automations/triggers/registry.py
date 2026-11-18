from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .gpio_input import GpioInputTrigger
from .octoprint_event import OctoprintEventTrigger
from .temperature import TemperatureTrigger

if TYPE_CHECKING:
    from .base import Trigger


@dataclass(frozen=True)
class TriggerDefinition:
    """Describes a type of automation trigger."""

    label: str
    """The name of the type of trigger."""

    implementation: type[Trigger]
    """The class implementing the trigger."""


TRIGGERS: dict[str, TriggerDefinition] = {
    "gpio_input": TriggerDefinition(label="GPIO Input", implementation=GpioInputTrigger),
    "temperature": TriggerDefinition(label="Temperature", implementation=TemperatureTrigger),
    "octoprint_event": TriggerDefinition(label="OctoPrint Event", implementation=OctoprintEventTrigger),
}
"""The supported types of automation triggers, by identifier."""
