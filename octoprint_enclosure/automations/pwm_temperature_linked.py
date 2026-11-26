from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.config import OutputId, SensorInputId, config_field
from octoprint_enclosure.utils import clamp

from .base import Automation, AutomationConfig

if TYPE_CHECKING:
    import logging
    from collections.abc import Sequence

    from .conditions import Condition


@dataclass(frozen=True)
class PwmTemperatureLinkedConfig(AutomationConfig):
    """The configuration of an automation that sets a PWM duty cycle from the reading of a linked temperature sensor.

    Between the first and the second temperature, the duty cycle changes linearly from the first to the second one.
    """

    type_help = (
        '<span class="label label-info">Info:</span> Sets the duty cycle of a PWM output from the temperature read by '
        "a sensor: duty A at temperature A, duty B at temperature B, in proportion between the two. It works while "
        "its conditions are satisfied, for example only during a print; when they stop being satisfied, the output "
        "is turned off."
    )

    output: OutputId = config_field(
        label="Controlled IO",
        help_text=("PWM output whose duty cycle follows the temperature. Configured in the Outputs tab."),
        widget="pwm_output",
    )
    """The id of the PWM output."""

    linked_temp_sensor: SensorInputId = config_field(
        label="Temperature Sensor",
        help_text="Sensor that reads the temperature. Configured in the Inputs tab.",
    )
    """The id of the input of the sensor that reads the temperature."""

    temperature_a: float = config_field(label="Temperature A", widget="temperature")
    """The temperature at which the output gets the first duty cycle."""

    duty_a: float = config_field(label="Duty A", min_value=0, max_value=100)
    """The duty cycle of the output at the first temperature, from 0 to 100."""

    temperature_b: float = config_field(label="Temperature B", widget="temperature")
    """The temperature at which the output gets the second duty cycle."""

    duty_b: float = config_field(label="Duty B", min_value=0, max_value=100)
    """The duty cycle of the output at the second temperature, from 0 to 100."""


class PwmTemperatureLinkedAutomation(Automation[PwmTemperatureLinkedConfig]):
    """An automation that sets the duty cycle of a PWM output from the reading of a linked temperature sensor."""

    config_class = PwmTemperatureLinkedConfig

    _running: bool
    """Whether the curve is driving its output."""

    def __init__(
        self,
        config: PwmTemperatureLinkedConfig,
        logger: logging.Logger,
        conditions: Sequence[Condition] = (),
    ) -> None:
        """Set up the PWM curve automation.

        Args:
            config (PwmTemperatureLinkedConfig): The configuration of the automation.
            logger (logging.Logger): The logger to write to.
            conditions (Sequence[Condition]): What must be true for the automation to act.

        """
        super().__init__(config, logger, conditions)
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the curve is driving its output."""
        return self._running

    def start(self) -> None:
        """Start driving the output."""
        self._running = True

    def stop(self) -> None:
        """Stop driving the output."""
        self._running = False

    def get_duty_cycle(self, temperature: float | None) -> float:
        """Work out the duty cycle of the output for a temperature.

        Args:
            temperature (float | None): The temperature read by the sensor, or None if it has none.

        Returns:
            float: The duty cycle, from 0 to 100.

        """
        config = self.config
        temperature_a, duty_a = config.temperature_a, config.duty_a
        temperature_b, duty_b = config.temperature_b, config.duty_b

        # Without a temperature, use the duty cycle of a very high temperature: full power if the duty cycle grows with
        # the temperature (as for a cooling fan), or off if it decreases (as for a heater)
        if temperature is None:
            if temperature_a == temperature_b:
                duty_cycle = 0
            elif duty_a == duty_b:
                duty_cycle = duty_a
            else:
                duty_cycle = 100 if (duty_b - duty_a) / (temperature_b - temperature_a) > 0 else 0
        # Below the first temperature the output is off
        elif temperature_a == temperature_b or temperature < temperature_a:
            duty_cycle = 0
        else:
            duty_cycle = (temperature - temperature_a) * (duty_b - duty_a) / (temperature_b - temperature_a) + duty_a

        return clamp(duty_cycle, 0, 100)
