from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, ClassVar, Mapping, Optional, Sequence, TypeVar, get_type_hints

from typing_extensions import override

from octoprint_enclosure.config import BaseConfig, OutputId, config_field
from octoprint_enclosure.utils import N_, Rgb

_ConfigT = TypeVar("_ConfigT", bound=BaseConfig)


@dataclass(frozen=True)
class OutputSetpointConfig(BaseConfig):
    """The setpoint of any output: one field for each field of the setpoints of the outputs.

    Only the fields of the setpoint of the output are set, and only when the setpoint is used: the others are None.
    """

    setpoint_visible_if: ClassVar[Mapping[str, Sequence[Any]]] = {}
    """When the setpoint is used: each field it names must have one of the values listed for it. Empty if always."""

    duty_cycle: Optional[float] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and float | None fails on Python < 3.10
        label=N_("Duty Cycle"),
        help_text=N_("Duty cycle the PWM is set to when it is turned on, between 0 and 100."),
        min_value=0,
        max_value=100,
        widget="output_setpoint",
    )
    """The duty cycle a PWM output is turned on to."""

    color: Optional[Rgb] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and Rgb | None fails on Python < 3.10
        default=Rgb(0, 0, 0),
        label=N_("Color"),
        help_text=N_("Color the LEDs are set to when they are turned on."),
        widget="output_setpoint",
    )
    """The color LEDs are turned on to."""

    target: Optional[float] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and float | None fails on Python < 3.10
        label=N_("Target"),
        help_text=N_("Value the thermostat is set to when it is turned on."),
        widget="output_setpoint",
    )
    """The target a thermostat is turned on to."""

    @classmethod
    @override
    def describe(cls) -> list[dict[str, Any]]:
        setpoint_names = {field.name for field in fields(OutputSetpointConfig)}
        descriptions = super().describe()
        setpoint_descriptions = [
            {**description, "visible_if": cls.setpoint_visible_if or None}
            for description in descriptions
            if description["name"] in setpoint_names
        ]
        other_descriptions = [description for description in descriptions if description["name"] not in setpoint_names]

        # The setpoint comes after the output it is for, and after the fields that say when it is used
        type_hints = get_type_hints(cls)
        last_index = max(
            (
                index
                for index, description in enumerate(other_descriptions)
                if type_hints[description["name"]] is OutputId or description["name"] in cls.setpoint_visible_if
            ),
            default=-1,
        )
        return [*other_descriptions[: last_index + 1], *setpoint_descriptions, *other_descriptions[last_index + 1 :]]


def config_with_setpoint_from_settings(
    config_class: type[_ConfigT],
    settings: dict,
    setpoint_classes: Mapping[int, type[BaseConfig]],
) -> _ConfigT:
    """Read a configuration from settings, with the setpoint of the output it names.

    Of the fields of the setpoint, only the ones that the output uses are read: none, for an output that is not
    there. A configuration without a setpoint is read as it is.

    Args:
        config_class (type[_ConfigT]): The dataclass of the configuration.
        settings (dict): The settings to read.
        setpoint_classes (Mapping[int, type[BaseConfig]]): The class of the setpoint of each output, by the id of the
            output.

    Returns:
        _ConfigT: The configuration.

    Raises:
        ValueError: If the settings are not valid.

    """
    has_setpoint = issubclass(config_class, OutputSetpointConfig)
    setpoint_names = {field.name for field in fields(OutputSetpointConfig)} if has_setpoint else set()

    # Read without the setpoint, to know the output
    config = config_class.from_settings(settings, unused_field_names=setpoint_names)
    if not setpoint_names:
        return config

    # Get the class of the setpoint of the output
    output_field_name = next(name for name, type_hint in get_type_hints(config_class).items() if type_hint is OutputId)
    setpoint_class = setpoint_classes.get(getattr(config, output_field_name))
    if setpoint_class is None:
        return config

    # Read again, with the fields of the setpoint that the output uses
    used_names = {field.name for field in fields(setpoint_class)}
    return config_class.from_settings(settings, unused_field_names=setpoint_names - used_names)
