from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Any, get_type_hints

from octoprint_enclosure.actions.base import ActionConfig
from octoprint_enclosure.actions.registry import ACTIONS
from octoprint_enclosure.automations.base import AutomationConfig
from octoprint_enclosure.automations.registry import AUTOMATIONS
from octoprint_enclosure.config import WIDGET_TYPES, OutputId
from octoprint_enclosure.inputs.config import InputConfig
from octoprint_enclosure.inputs.registry import INPUTS
from octoprint_enclosure.outputs import ThermostatDeviceType, ThermostatSetpoint
from octoprint_enclosure.outputs.config import OutputConfig
from octoprint_enclosure.outputs.registry import OUTPUTS
from octoprint_enclosure.utils import MeasurementType

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from octoprint_enclosure.config import BaseConfig


_DEVICE_TYPES_BY_MEASUREMENT_TYPE = {
    measurement_type.value: [
        device_type.value for device_type in ThermostatDeviceType if device_type.measurement_type is measurement_type
    ]
    for measurement_type in MeasurementType
}
"""The device types of a thermostat that act on each type of measurement."""


class SettingsForms:
    """The forms of the settings page, described from the configuration classes of the plugin."""

    forms: dict[str, list[dict[str, Any]]]
    """The form of an item of each list of the settings, by the name of the list.

    A form is the list of its fields, in the order they are shown. Each field is a dictionary that describes
    the field. Two kinds of field hold other forms, under one more key:

    - "variants", for a field that chooses other fields: for each of its choices, the form with the fields shown
      after it.
    - "list_item_form", for a field that is a list of items, which can be added and removed: the form of an item.

    Examples:
        A form with a plain field, a field with two choices and a list of items::

            [
                {"name": "label", ...},
                {
                    "name": "shape",
                    ...,
                    "variants": [
                        {"value": "circle", ..., "form": [{"name": "radius", ...}]},
                        {"value": "square", ..., "form": [{"name": "side", ...}]},
                    ],
                },
                {"name": "notes", ..., "list_item_form": [{"name": "text", ...}]},
            ]
    """

    _widget_data: dict[str, Callable[[str, type[BaseConfig]], dict[str, Any]]]
    """The method that gives the data a widget needs to be drawn, by the name of the widget."""

    def __init__(self) -> None:
        """Set up the settings forms.

        Raises:
            TypeError: If a widget that this class gives data for is not a widget of the settings.

        """
        # Widget data, checked for unknown widgets
        self._widget_data = {
            "output_setpoint": self._output_setpoint_data,
            "thermostat_sensor": self._thermostat_sensor_data,
        }
        unknown_widgets = sorted(set(self._widget_data) - set(WIDGET_TYPES))
        if unknown_widgets:
            msg = f"Unknown widgets: {', '.join(unknown_widgets)}"
            raise TypeError(msg)

        # Forms
        self.forms = {
            "rpi_inputs": self._describe_form(InputConfig, INPUTS),
            "rpi_outputs": self._describe_form(OutputConfig, OUTPUTS),
            "actions": self._describe_form(ActionConfig, ACTIONS),
            "automations": self._describe_form(AutomationConfig, AUTOMATIONS),
        }

    ##########
    ### Forms
    ##########

    def _describe_form(self, config_class: type[BaseConfig], type_classes: Mapping[Any, Any]) -> list[dict[str, Any]]:
        descriptions: list[dict[str, Any]] = []
        for description in config_class.describe():
            if description["type"] == "bool" and description["choices"] is None:
                empty: Any = False
            elif description["type"] == "FrozenSet[str]":
                empty = []
            else:
                empty = ""

            get_widget_data = self._widget_data.get(description["widget"])
            widget_data = get_widget_data(description["name"], config_class) if get_widget_data is not None else {}
            descriptions.append({**description, **widget_data, "empty": empty})

        if type_classes:
            names = [description["name"] for description in descriptions]
            variants = []
            for type_member, type_class in type_classes.items():
                form = self._describe_form(type_class.config_class, getattr(type_class, "config_type_classes", {}))

                for nested_item_list in getattr(type_class, "nested_item_lists", ()):
                    form.append(
                        {
                            "name": nested_item_list.settings_key,
                            "label": nested_item_list.item_label,
                            "default": None,
                            "empty": [],
                            "list_item_form": self._describe_form(
                                nested_item_list.shared_item_config_class,
                                nested_item_list.item_type_classes,
                            ),
                        },
                    )

                variants.append(
                    {
                        "value": type_member.value,
                        "label": type_member.label,
                        "help_text": type_class.config_class.type_help,
                        "form": [field for field in form if field["name"] not in names],
                    },
                )

            descriptions[names.index(config_class.type_field_name)]["variants"] = variants

        return descriptions

    ##########
    ### Widgets
    ##########

    def _output_setpoint_data(self, field_name: str, config_class: type[BaseConfig]) -> dict[str, Any]:
        output_field_name = next(
            name for name, type_hint in get_type_hints(config_class).items() if type_hint is OutputId
        )
        output_types = [
            output_type.value
            for output_type, output_class in OUTPUTS.items()
            if field_name in {field.name for field in fields(output_class.setpoint_class)}
        ]
        is_thermostat_target = field_name in {field.name for field in fields(ThermostatSetpoint)}
        return {
            "output_field": output_field_name,
            "visible_if_output_type": {output_field_name: output_types},
            "device_types_by_measurement_type": _DEVICE_TYPES_BY_MEASUREMENT_TYPE if is_thermostat_target else None,
        }

    def _thermostat_sensor_data(self, _field_name: str, config_class: type[BaseConfig]) -> dict[str, Any]:
        device_type_field_name = next(
            name for name, type_hint in get_type_hints(config_class).items() if type_hint is ThermostatDeviceType
        )
        return {
            "device_type_field": device_type_field_name,
            "device_types_by_measurement_type": _DEVICE_TYPES_BY_MEASUREMENT_TYPE,
        }
