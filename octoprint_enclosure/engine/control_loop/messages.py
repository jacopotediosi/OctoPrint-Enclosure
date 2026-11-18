from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import threading

    from octoprint_enclosure.automations import AutomationEvent, RuleAutomation, ToggleTimerAutomation


class Message:
    """A message to the Control Loop thread."""


##########
### Something has happened
##########


@dataclass(frozen=True)
class Started(Message):
    """The Control Loop started."""


@dataclass(frozen=True)
class NewReading(Message):
    """A sensor has a new reading."""

    sensor_id: int
    """The id of the input of the sensor."""


@dataclass(frozen=True)
class SensorFailed(Message):
    """A sensor stopped working."""

    sensor_id: int
    """The id of the input of the sensor."""


@dataclass(frozen=True)
class SettingsLoaded(Message):
    """New settings were loaded."""


##########
### Something must be done
##########


@dataclass(frozen=True)
class Tick(Message):
    """Time to take all the decisions again."""


@dataclass(frozen=True)
class Stop(Message):
    """The Control Loop must stop."""


@dataclass(frozen=True)
class SetThermostatTarget(Message):
    """The target of a thermostat must be set."""

    index_id: int
    """The id of the thermostat."""

    target: float | None
    """The target temperature or humidity, or None to turn the thermostat off."""

    origin: str
    """Who asks for it, e.g. "API", "ENC", etc."""

    done: threading.Event | None = None
    """Set once the target is applied and the device of the thermostat is switched, or None if nobody waits for
    it."""


@dataclass(frozen=True)
class WaitForThermostatTarget(Message):
    """The paused print must wait until a thermostat reaches its target."""

    index_id: int
    """The id of the thermostat that must reach its target."""


@dataclass(frozen=True)
class SetAutomationEnabled(Message):
    """An automation must be enabled or disabled."""

    index_id: int
    """The id of the automation."""

    enabled: bool
    """Whether to enable the automation, or to disable it."""

    done: threading.Event | None = None
    """Set once the automation is enabled or disabled, or None if nobody waits for it."""


@dataclass(frozen=True)
class RunAutomationRuleReactions(Message):
    """An automation rule must run its reactions."""

    rule: RuleAutomation
    """The rule whose reactions must be run."""

    event: AutomationEvent
    """What started the rule."""


@dataclass(frozen=True)
class SwitchToggleTimerOutput(Message):
    """The output of a toggle timer automation must be turned on or off."""

    automation: ToggleTimerAutomation
    """The toggle timer automation."""

    turn_on: bool
    """Whether to turn the output on now, or off."""


@dataclass(frozen=True)
class UpdateUi(Message):
    """The UI has to be updated."""
