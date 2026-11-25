from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import check_all_members_mapped

from .base import TriggerType
from .gpio_input import GpioInputTrigger
from .octoprint_event import OctoprintEventTrigger
from .temperature import TemperatureTrigger

if TYPE_CHECKING:
    from .base import Trigger

TRIGGERS: dict[TriggerType, type[Trigger]] = {
    TriggerType.GPIO_INPUT: GpioInputTrigger,
    TriggerType.TEMPERATURE: TemperatureTrigger,
    TriggerType.OCTOPRINT_EVENT: OctoprintEventTrigger,
}
"""The class implementing each type of automation trigger."""

# Check that TRIGGERS contains every type of automation trigger
check_all_members_mapped(TRIGGERS, TriggerType)
