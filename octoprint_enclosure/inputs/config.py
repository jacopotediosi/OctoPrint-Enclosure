from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.config import BaseConfig, config_field
from octoprint_enclosure.utils import N_, LabeledEnum, LabeledValue


class PullResistor(LabeledEnum):
    """The internal resistor that pulls a GPIO pin up or down."""

    UP = LabeledValue(value="input_pull_up", label=N_("Input Pullup"))
    DOWN = LabeledValue(value="input_pull_down", label=N_("Input Pulldown"))
    OFF = LabeledValue(value="none", label=N_("None"))


class InputType(LabeledEnum):
    """The type of an input."""

    GPIO = LabeledValue(value="gpio", label=N_("GPIO Input / Filament Sensor"))
    TEMPERATURE_SENSOR = LabeledValue(value="temperature_sensor", label=N_("Temperature Sensor"))


@dataclass(frozen=True)
class InputConfig(BaseConfig):
    """The configuration shared by all the inputs."""

    type_field_name = "input_type"

    index_id: int = config_field(label=N_("Id"), widget="id")
    """The id of the input."""

    label: str = config_field(label=N_("Label"), compare=False)
    """The name of the input."""

    input_type: InputType = config_field(label=N_("Input Type"))
    """The type of the input."""
