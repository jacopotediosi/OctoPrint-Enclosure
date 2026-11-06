from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from octoprint_enclosure.settings import REQUIRED, BaseConfig


class PullResistor(Enum):
    """The internal resistor that pulls a GPIO pin up or down."""

    UP = "input_pull_up"
    DOWN = "input_pull_down"
    OFF = ""


class InputType(Enum):
    """The type of an input."""

    GPIO = "gpio"
    TEMPERATURE_SENSOR = "temperature_sensor"


@dataclass(frozen=True)
class InputConfig(BaseConfig):
    """The configuration shared by all the inputs."""

    index_id: int = REQUIRED
    """The id of the input."""

    input_type: InputType = REQUIRED
    """The type of the input."""

    label: str = field(default="", compare=False)
    """The name of the input."""
