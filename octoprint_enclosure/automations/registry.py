from __future__ import annotations

from typing import TYPE_CHECKING

from .filament import FilamentAutomation
from .pwm_temperature_linked import PwmTemperatureLinkedAutomation
from .rule import RuleAutomation
from .toggle_timer import ToggleTimerAutomation

if TYPE_CHECKING:
    from .base import Automation

AUTOMATIONS: dict[str, type[Automation]] = {
    "rule": RuleAutomation,
    "filament": FilamentAutomation,
    "pwm_temperature_linked": PwmTemperatureLinkedAutomation,
    "toggle_timer": ToggleTimerAutomation,
}
"""The supported types of automations, by identifier."""
