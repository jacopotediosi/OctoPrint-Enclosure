from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, FrozenSet

from typing_extensions import override

from octoprint_enclosure.automations.events import OctoprintEvent
from octoprint_enclosure.config import BaseConfig, config_field
from octoprint_enclosure.utils import N_

from .base import Trigger

if TYPE_CHECKING:
    from octoprint_enclosure.automations.events import AutomationEvent


@dataclass(frozen=True)
class OctoprintEventTriggerConfig(BaseConfig):
    """The configuration of an automation trigger on the events of OctoPrint."""

    octoprint_events: FrozenSet[str] = config_field(  # noqa: UP006 - BaseConfig.from_settings evaluates, and frozenset[str] fails on Python < 3.9
        label=N_("Events"),
        help_text=N_("OctoPrint events that run the automation."),
        widget="octoprint_events",
    )
    """The names of the OctoPrint events that start the automation."""


class OctoprintEventTrigger(Trigger[OctoprintEventTriggerConfig]):
    """An automation trigger on the events of OctoPrint."""

    config_class = OctoprintEventTriggerConfig

    @override
    def matches(self, event: AutomationEvent) -> bool:
        return isinstance(event, OctoprintEvent) and event.name in self.config.octoprint_events
