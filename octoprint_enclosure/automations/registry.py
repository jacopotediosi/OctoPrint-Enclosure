from __future__ import annotations

from typing import TYPE_CHECKING

from .filament import FilamentAutomation
from .pwm_temperature_linked import PwmTemperatureLinkedAutomation
from .rule import RuleAutomation

if TYPE_CHECKING:
    from .base import Automation

AUTOMATIONS: dict[str, type[Automation]] = {
    "rule": RuleAutomation,
    "filament": FilamentAutomation,
    "pwm_temperature_linked": PwmTemperatureLinkedAutomation,
}
"""The supported types of automations, by identifier."""
