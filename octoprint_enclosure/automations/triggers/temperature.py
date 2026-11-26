from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.automations.events import ReadingEvent
from octoprint_enclosure.config import BaseConfig, SensorInputId, config_field
from octoprint_enclosure.utils import N_

from .base import Trigger

if TYPE_CHECKING:
    from octoprint_enclosure.automations.events import AutomationEvent


@dataclass(frozen=True)
class TemperatureTriggerConfig(BaseConfig):
    """The configuration of an automation trigger on the temperature read by a sensor."""

    linked_temp_sensor: SensorInputId = config_field(
        label=N_("Temperature Sensor"),
        help_text=N_("Sensor that reads the temperature. Configured in the Inputs tab."),
    )
    """The id of the input of the linked sensor."""

    alarm_set_temp: float = config_field(
        label=N_("Set Temperature"),
        help_text=N_("Temperature above which the automation runs."),
        widget="temperature",
    )
    """The temperature above which the automation starts."""

    repeat_while_above: bool = config_field(
        default=False,
        label=N_("Repeat while above"),
        help_text=N_(
            "Run the automation at every reading above the set temperature, instead of only when the temperature goes "
            "above it the first time.",
        ),
    )
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
        if not isinstance(event, ReadingEvent) or event.index_id != self.config.linked_temp_sensor:
            return False

        temperature = event.reading.temperature
        if temperature is None:
            return False

        was_above = self._above
        self._above = temperature > self.config.alarm_set_temp

        return self._above and (self.config.repeat_while_above or not was_above)
