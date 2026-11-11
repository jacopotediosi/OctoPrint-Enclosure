from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from octoprint_enclosure.settings import BaseConfig
from octoprint_enclosure.utils import Rgb

from .color import ColorSetpoint
from .pwm import PwmSetpoint
from .thermostat import ThermostatSetpoint


@dataclass(frozen=True)
class OutputSetpointConfig(BaseConfig):
    """The setpoint of any output: one field for each field of the setpoints of the outputs."""

    duty_cycle: float = 0
    """The duty cycle a PWM output is turned on to."""

    color: Rgb = Rgb(0, 0, 0)
    """The color LEDs are turned on to."""

    target: Optional[float] = None  # noqa: UP045 - BaseConfig.from_settings evaluates, and float | None fails on Python < 3.10
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
