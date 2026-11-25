from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, ClassVar, Mapping, Optional, Sequence, get_type_hints

from typing_extensions import override

from octoprint_enclosure.settings import BaseConfig, OutputId, setting
from octoprint_enclosure.utils import Rgb

from .color import ColorSetpoint
from .pwm import PwmSetpoint
from .thermostat import ThermostatSetpoint


@dataclass(frozen=True)
class OutputSetpointConfig(BaseConfig):
    """The setpoint of any output: one field for each field of the setpoints of the outputs."""

    setpoint_visible_if: ClassVar[Mapping[str, Sequence[Any]]] = {}
    """When the setpoint is used: each field it names must have one of the values listed for it. Empty if always."""

    duty_cycle: float = setting(
        default=0,
        label="Duty Cycle",
        help_text="Duty cycle the PWM is set to when it is turned on, between 0 and 100.",
        min_value=0,
        max_value=100,
        widget="output_setpoint",
    )
    """The duty cycle a PWM output is turned on to."""

    color: Rgb = setting(
        default=Rgb(0, 0, 0),
        label="Color",
        help_text="Color the LEDs are set to when they are turned on.",
        widget="output_setpoint",
    )
    """The color LEDs are turned on to."""

    target: Optional[float] = setting(  # noqa: UP045 - BaseConfig.from_settings evaluates, and float | None fails on Python < 3.10
        optional=True,
        label="Target",
        help_text="Value the thermostat is set to when it is turned on.",
        widget="output_setpoint",
    )
    """The target a thermostat is turned on to, or None if it is not set."""

    def __post_init__(self) -> None:
        """Check the setpoints as the outputs read them.

        Raises:
            ValueError: If a setpoint is not valid for its output.

        """
        PwmSetpoint(self.duty_cycle)
        ColorSetpoint(self.color)
        if self.target is not None:
            ThermostatSetpoint(self.target)

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
