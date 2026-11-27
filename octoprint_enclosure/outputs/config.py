from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from octoprint_enclosure.config import BaseConfig, config_field
from octoprint_enclosure.utils import N_, LabeledEnum, LabeledValue


class OutputType(LabeledEnum):
    """The type of an output."""

    REGULAR = LabeledValue(value="regular", label=N_("Regular IO"))
    PWM = LabeledValue(value="pwm", label="PWM")
    NEOPIXEL_INDIRECT = LabeledValue(value="neopixel_indirect", label=N_("NeoPixel Indirect"))
    NEOPIXEL_DIRECT = LabeledValue(value="neopixel_direct", label=N_("NeoPixel Direct"))
    LEDSTRIP = LabeledValue(value="ledstrip", label=N_("RGB LED Strip"))
    THERMOSTAT = LabeledValue(value="temp_hum_control", label=N_("Thermostat"))


@dataclass(frozen=True)
class OutputConfig(BaseConfig):
    """The configuration shared by all the outputs."""

    type_field_name = "output_type"

    index_id: int = config_field(label=N_("Id"), widget="id")
    """The id of the output."""

    label: str = config_field(label=N_("Label"), compare=False)
    """The name of the output."""

    output_type: OutputType = config_field(label=N_("Output Type"), in_summary=True)
    """The type of the output."""

    hide_btn_ui: bool = config_field(default=False, label=N_("Hide in tab"), compare=False)
    """Whether the button of the output is hidden in the Enclosure tab."""

    show_on_navbar: Optional[bool] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and bool | None fails on Python < 3.10
        default=False,
        label=N_("Show in navbar"),
        visible_if={"output_type": ["regular"]},
        compare=False,
    )
    """Whether the output has a button in the navbar, or None if it is of a type that can't have one."""
