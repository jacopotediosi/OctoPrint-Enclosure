from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.automations.events import ReadingsEvent
from octoprint_enclosure.settings import REQUIRED, BaseConfig, SensorInputId

from .base import Trigger

if TYPE_CHECKING:
    from octoprint_enclosure.automations.events import AutomationEvent


@dataclass(frozen=True)
class TemperatureTriggerConfig(BaseConfig):
    """The configuration of an automation trigger on the temperature read by a sensor."""

    linked_temp_sensor: SensorInputId = REQUIRED
    """The id of the input of the linked sensor."""

    alarm_set_temp: float = REQUIRED
    """The temperature above which the automation starts."""

    repeat_while_above: bool = REQUIRED
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

    @override
    def matches(self, event: AutomationEvent) -> bool:
        if not isinstance(event, ReadingsEvent) or event.index_id != self.config.linked_temp_sensor:
            return False

        reading = event.readings.get(self.config.linked_temp_sensor)
        temperature = None if reading is None else reading.temperature
        if temperature is None:
            return False

        was_above = self._above
        self._above = temperature > self.config.alarm_set_temp

        return self._above and (self.config.repeat_while_above or not was_above)
