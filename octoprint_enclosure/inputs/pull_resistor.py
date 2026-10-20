from __future__ import annotations

from enum import Enum


class PullResistor(Enum):
    """The internal resistor that pulls a GPIO pin up or down."""

    UP = "input_pull_up"
    DOWN = "input_pull_down"
