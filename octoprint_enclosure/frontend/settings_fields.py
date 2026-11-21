from __future__ import annotations

from typing import TYPE_CHECKING, Any

from octoprint_enclosure.actions.registry import ACTIONS
from octoprint_enclosure.automations.conditions.registry import CONDITIONS
from octoprint_enclosure.automations.reactions.registry import REACTIONS
from octoprint_enclosure.automations.registry import AUTOMATIONS
from octoprint_enclosure.automations.triggers.registry import TRIGGERS
from octoprint_enclosure.inputs.gpio.gpio_input import GpioInput
from octoprint_enclosure.inputs.sensors.registry import SENSORS
from octoprint_enclosure.outputs.registry import OUTPUTS

if TYPE_CHECKING:
    from collections.abc import Iterable

    from octoprint_enclosure.settings import BaseConfig


def describe_settings_fields() -> dict[str, list[dict[str, Any]]]:
    """Describe the fields of the items of each list of the settings.

    Returns:
        dict[str, list[dict[str, Any]]]: The description of each field of the items of "rpi_inputs", "rpi_outputs",
            "actions" and "automations", with these keys:

            - "name" (str): The name of the field.
            - "default" (Any): The value of the field in a new item, as it is saved, None if it starts empty.
            - "empty" (Any): The value of the field when it is empty: False for a checkbox, an empty list for a set
              of values or a list of items, an empty text for the others.
            - "fields" (list[dict[str, Any]] | None): The description of each field of the items of a field that is
              a list of items.

    """
    return {
        "rpi_inputs": _describe_fields(
            [GpioInput.config_class, *(sensor.implementation.config_class for sensor in SENSORS.values())],
        ),
        "rpi_outputs": _describe_fields(output_class.config_class for output_class in OUTPUTS.values()),
        "actions": _describe_fields(action.implementation.config_class for action in ACTIONS.values()),
        "automations": [
            *_describe_fields(
                [
                    *(automation.implementation.config_class for automation in AUTOMATIONS.values()),
                    *(trigger.implementation.config_class for trigger in TRIGGERS.values()),
                ],
            ),
            {
                "name": "conditions",
                "default": None,
                "empty": [],
                "fields": _describe_fields(condition.implementation.config_class for condition in CONDITIONS.values()),
            },
            {
                "name": "reactions",
                "default": None,
                "empty": [],
                "fields": _describe_fields(reaction.implementation.config_class for reaction in REACTIONS.values()),
            },
        ],
    }


def _describe_fields(config_classes: Iterable[type[BaseConfig]]) -> list[dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for config_class in config_classes:
        for description in config_class.describe():
            if description["type"] == "bool" and description["choices"] is None:
                empty: Any = False
            elif description["type"] == "FrozenSet[str]":
                empty = []
            else:
                empty = ""

            fields.setdefault(
                description["name"],
                {"name": description["name"], "default": description["default"], "empty": empty, "fields": None},
            )

    return list(fields.values())
