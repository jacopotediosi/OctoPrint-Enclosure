from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.core import BaseConfig

from .base import Trigger


@dataclass(frozen=True)
class TemperatureTriggerConfig(BaseConfig):
    """The configuration of an automation trigger on the temperature read by a sensor."""

    linked_temp_sensor: int
    """The id of the input of the linked sensor."""

    alarm_set_temp: float
    """The temperature above which the automation starts."""

    repeat_while_above: bool
    """Whether the automation starts at every temperature reading above the threshold, instead of only when the
    temperature goes above it the first time."""


class TemperatureTrigger(Trigger[TemperatureTriggerConfig]):
    """An automation trigger on the temperature read by a sensor."""

    config_class = TemperatureTriggerConfig

    _above: bool
    """Whether the last temperature read was above the threshold."""

    def __init__(self, config: TemperatureTriggerConfig) -> None:
        """Set up the temperature automation trigger.

        Args:
            config (TemperatureTriggerConfig): The configuration of the automation trigger.

        """
        super().__init__(config)
        self._above = False

    def matches_temperature(self, temperature: float | None) -> bool:
        """Check whether a temperature of the sensor starts the automation.

        Args:
            temperature (float | None): The temperature, or None if the sensor has none.

        Returns:
            bool: Whether the temperature starts the automation.

        """
        if temperature is None:
            return False

        was_above = self._above
        self._above = temperature > self.config.alarm_set_temp

        return self._above and (self.config.repeat_while_above or not was_above)
