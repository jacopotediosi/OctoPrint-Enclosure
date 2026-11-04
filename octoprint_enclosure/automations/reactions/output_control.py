from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from octoprint_enclosure.core import REQUIRED, BaseConfig
from octoprint_enclosure.outputs import ColorSetpoint, PwmSetpoint, ThermostatSetpoint
from octoprint_enclosure.utils import Rgb

from .base import Reaction


class OutputSetState(Enum):
    """What to do with an output."""

    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"


@dataclass(frozen=True)
class OutputControlConfig(BaseConfig):
    """The configuration of an automation reaction that controls an output."""

    controlled_io: int = REQUIRED
    """The id of the output to control."""

    controlled_io_set_state: OutputSetState = REQUIRED
    """What to do with the output."""

    duty_cycle: float = 0
    """The duty cycle a PWM output is turned on to."""

    color: Rgb = Rgb(0, 0, 0)
    """The color LEDs are turned on to."""

    target: float = 0
    """The target a thermostat is turned on to."""

    def __post_init__(self) -> None:
        """Check the setpoints as the outputs read them.

        Raises:
            ValueError: If a setpoint is not valid for its output.

        """
        PwmSetpoint(self.duty_cycle)
        ColorSetpoint(self.color)
        ThermostatSetpoint(self.target)


class OutputControlReaction(Reaction[OutputControlConfig]):
    """An automation reaction that controls an output."""

    config_class = OutputControlConfig
