from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from octoprint_enclosure.automations import AutomationEvent, ConditionsState
    from octoprint_enclosure.inputs import Reading


class Decision(ABC):
    """A kind of decision of the control loop."""

    @abstractmethod
    def decide(self, readings: Mapping[int, Reading], conditions_state: ConditionsState) -> None:
        """Decide what has to be done now, e.g. whether an output has to be turned on, etc.

        The decision is taken from the state of the current situation: the last readings of the sensors, the
        current state of the automation conditions, etc.

        Args:
            readings (Mapping[int, Reading]): The last reading of the sensors, by the id of their input.
            conditions_state (ConditionsState): The current state of the things that the automation conditions check.

        """

    @abstractmethod
    def react(self, event: AutomationEvent, conditions_state: ConditionsState) -> None:
        """React to an automation event.

        Args:
            event (AutomationEvent): The automation event to react to.
            conditions_state (ConditionsState): The current state of the things that the automation conditions check.

        """
