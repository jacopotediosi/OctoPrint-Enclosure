from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .filament import FilamentAutomation
from .pwm_temperature_linked import PwmTemperatureLinkedAutomation
from .rule import RuleAutomation
from .toggle_timer import ToggleTimerAutomation

if TYPE_CHECKING:
    from .base import Automation


@dataclass(frozen=True)
class AutomationDefinition:
    """Describes a type of automation."""

    label: str
    """The name of the type of automation."""

    implementation: type[Automation]
    """The class implementing the automation."""


AUTOMATIONS: dict[str, AutomationDefinition] = {
    "rule": AutomationDefinition(label="Rule (Trigger-Reaction)", implementation=RuleAutomation),
    "filament": AutomationDefinition(label="Filament Sensor", implementation=FilamentAutomation),
    "pwm_temperature_linked": AutomationDefinition(
        label="PWM Linked to Temperature",
        implementation=PwmTemperatureLinkedAutomation,
    ),
    "toggle_timer": AutomationDefinition(label="Toggle Timer", implementation=ToggleTimerAutomation),
}
"""The supported types of automations, by identifier."""
