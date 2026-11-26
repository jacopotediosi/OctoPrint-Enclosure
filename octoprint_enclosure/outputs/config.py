from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from octoprint_enclosure.settings import BaseConfig, setting
from octoprint_enclosure.utils import LabeledEnum, LabeledValue


class OutputType(LabeledEnum):
    """The type of an output."""

    REGULAR = LabeledValue(value="regular", label="Regular IO")
    PWM = LabeledValue(value="pwm", label="PWM")
    NEOPIXEL_INDIRECT = LabeledValue(value="neopixel_indirect", label="NeoPixel Indirect")
    NEOPIXEL_DIRECT = LabeledValue(value="neopixel_direct", label="NeoPixel Direct")
    LEDSTRIP = LabeledValue(value="ledstrip", label="RGB LED Strip")
    THERMOSTAT = LabeledValue(value="temp_hum_control", label="Thermostat")


@dataclass(frozen=True)
class OutputConfig(BaseConfig):
    """The configuration shared by all the outputs."""

    type_field_name = "output_type"

    index_id: int = setting(label="Id", widget="id")
    """The id of the output."""

    label: str = setting(optional=True, label="Label", compare=False)
    """The name of the output."""

    output_type: OutputType = setting(label="Output Type")
    """The type of the output."""

    hide_btn_ui: bool = setting(default=False, label="Hide in tab", compare=False)
    """Whether the button of the output is hidden in the Enclosure tab."""

    show_on_navbar: Optional[bool] = setting(  # noqa: UP045 - BaseConfig.from_settings evaluates, and bool | None fails on Python < 3.10
        default=False,
        label="Show in navbar",
        visible_if={"output_type": ["regular"]},
        compare=False,
    )
    """Whether the output has a button in the navbar, or None if it is of a type that can't have one."""
