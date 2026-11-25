from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.settings import BaseConfig, setting
from octoprint_enclosure.utils import LabeledEnum, LabeledValue


class PullResistor(LabeledEnum):
    """The internal resistor that pulls a GPIO pin up or down."""

    UP = LabeledValue(value="input_pull_up", label="Input Pullup")
    DOWN = LabeledValue(value="input_pull_down", label="Input Pulldown")
    OFF = LabeledValue(value="none", label="None")


class InputType(LabeledEnum):
    """The type of an input."""

    GPIO = LabeledValue(value="gpio", label="GPIO Input / Filament Sensor")
    TEMPERATURE_SENSOR = LabeledValue(value="temperature_sensor", label="Temperature Sensor")


@dataclass(frozen=True)
class InputConfig(BaseConfig):
    """The configuration shared by all the inputs."""

    type_field_name = "input_type"

    index_id: int = setting(label="Id", widget="id")
    """The id of the input."""

    label: str = setting(optional=True, label="Label", compare=False)
    """The name of the input."""

    input_type: InputType = setting(label="Input Type")
    """The type of the input."""
