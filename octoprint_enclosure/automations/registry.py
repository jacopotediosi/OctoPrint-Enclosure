from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import check_all_members_mapped

from .base import AutomationType
from .filament import FilamentAutomation
from .pwm_temperature_linked import PwmTemperatureLinkedAutomation
from .rule import RuleAutomation
from .toggle_timer import ToggleTimerAutomation

if TYPE_CHECKING:
    from .base import Automation

AUTOMATIONS: dict[AutomationType, type[Automation]] = {
    AutomationType.RULE: RuleAutomation,
    AutomationType.FILAMENT: FilamentAutomation,
    AutomationType.PWM_TEMPERATURE_LINKED: PwmTemperatureLinkedAutomation,
    AutomationType.TOGGLE_TIMER: ToggleTimerAutomation,
}
"""The class implementing each type of automation."""

# Check that AUTOMATIONS contains every type of automation
check_all_members_mapped(AUTOMATIONS, AutomationType)
