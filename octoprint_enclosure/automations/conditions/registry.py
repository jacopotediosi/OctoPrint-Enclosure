from __future__ import annotations

from typing import TYPE_CHECKING

from .print_job import PrintJobCondition

if TYPE_CHECKING:
    from .base import Condition

CONDITIONS: dict[str, type[Condition]] = {
    "print_job": PrintJobCondition,
}
"""The supported types of automation conditions, by identifier."""


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
        condition_type = condition_settings.get("condition_type", "")
        condition_class = CONDITIONS.get(condition_type)
        if condition_class is None:
            msg = f"Unsupported condition type: {condition_type!r}"
            raise ValueError(msg)
        conditions.append(condition_class.from_settings(condition_settings))
    return conditions
