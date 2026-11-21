from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import ConditionConfig
from .print_job import PrintJobCondition

if TYPE_CHECKING:
    from .base import Condition


@dataclass(frozen=True)
class ConditionDefinition:
    """Describes a type of automation condition."""

    label: str
    """The name of the type of condition."""

    implementation: type[Condition]
    """The class implementing the condition."""


CONDITIONS: dict[str, ConditionDefinition] = {
    "print_job": ConditionDefinition(label="Print Job", implementation=PrintJobCondition),
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
        condition_config = ConditionConfig.from_settings(condition_settings)
        condition_definition = CONDITIONS.get(condition_config.condition_type)
        if condition_definition is None:
            msg = f"Unsupported condition type: {condition_config.condition_type!r}"
            raise ValueError(msg)
        conditions.append(condition_definition.implementation.from_settings(condition_settings))
    return conditions
