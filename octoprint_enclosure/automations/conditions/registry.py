from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import check_all_members_mapped

from .base import ConditionConfig, ConditionType
from .print_job import PrintJobCondition

if TYPE_CHECKING:
    from .base import Condition

CONDITIONS: dict[ConditionType, type[Condition]] = {
    ConditionType.PRINT_JOB: PrintJobCondition,
}
"""The class implementing each type of automation condition."""

# Check that CONDITIONS contains every type of automation condition
check_all_members_mapped(CONDITIONS, ConditionType)


def conditions_from_settings(automation_settings: dict) -> list[Condition]:
    """Create the conditions of an automation from its settings.

    Args:
        automation_settings (dict): The settings of the automation.

    Returns:
        list[Condition]: The conditions of the automation, in order.

    Raises:
        ValueError: If the automation settings contain invalid conditions.

    """
    conditions_settings = automation_settings.get("conditions", [])
    if not isinstance(conditions_settings, list) or not all(isinstance(item, dict) for item in conditions_settings):
        msg = "conditions is not a list of conditions"
        raise ValueError(msg)

    conditions = []
    for condition_settings in conditions_settings:
        condition_config = ConditionConfig.from_settings(condition_settings)
        conditions.append(CONDITIONS[condition_config.condition_type].from_settings(condition_settings))
    return conditions
