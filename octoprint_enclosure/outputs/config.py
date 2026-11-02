from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from octoprint_enclosure.core import REQUIRED, BaseConfig


class OutputType(Enum):
    """The type of an output."""

    REGULAR = "regular"
    PWM = "pwm"
    NEOPIXEL_INDIRECT = "neopixel_indirect"
    NEOPIXEL_DIRECT = "neopixel_direct"
    LEDSTRIP = "ledstrip"
    THERMOSTAT = "temp_hum_control"


@dataclass(frozen=True)
class OutputConfig(BaseConfig):
    """The configuration shared by all the outputs."""

    index_id: int = REQUIRED
    """The id of the output."""

    output_type: OutputType = REQUIRED
    """The type of the output."""

    label: str = field(default="", compare=False)
    """The name of the output."""

    hide_btn_ui: bool = field(default=False, compare=False)
    """Whether the button of the output is hidden in the Enclosure tab."""

    show_on_navbar: bool = field(default=False, compare=False)
    """Whether the output has a button in the navbar."""
