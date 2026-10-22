from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.utils import clamp

from .base import Automation


@dataclass(frozen=True)
class PwmTemperatureLinkedConfig(BaseConfig):
    """The configuration of an automation that sets a PWM duty cycle from the reading of a linked temperature sensor.

    Between the first and the second temperature, the duty cycle changes linearly from the first to the second one.
    """

    output: int
    """The id of the PWM output."""

    linked_temp_sensor: int
    """The id of the input of the sensor that reads the temperature."""

    temperature_a: float
    """The temperature at which the output gets the first duty cycle."""

    duty_a: float
    """The duty cycle of the output at the first temperature, from 0 to 100."""

    temperature_b: float
    """The temperature at which the output gets the second duty cycle."""

    duty_b: float
    """The duty cycle of the output at the second temperature, from 0 to 100."""


class PwmTemperatureLinkedAutomation(Automation[PwmTemperatureLinkedConfig]):
    """An automation that sets the duty cycle of a PWM output from the reading of a linked temperature sensor."""

    config_class = PwmTemperatureLinkedConfig

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
