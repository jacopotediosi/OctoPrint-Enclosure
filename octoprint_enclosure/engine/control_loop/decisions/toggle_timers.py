from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.automations import AutomationError, OutputSetState, ToggleTimerAutomation
from octoprint_enclosure.engine.control_loop.messages import SwitchToggleTimerOutput

from .base import Decision

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from octoprint_enclosure.automations import AutomationEvent, Automations, ConditionsState
    from octoprint_enclosure.engine.control_loop.messages import Message
    from octoprint_enclosure.engine.scheduler import Scheduler
    from octoprint_enclosure.inputs import Reading

    from .output_control import OutputControl


class ToggleTimerDecision(Decision):
    """The decision regarding the toggle timers.

    Each timer turns an output on and off in turn, while its conditions are satisfied.
    """

    _automations: Automations
    _scheduler: Scheduler
    _output_control: OutputControl
    _logger: logging.Logger

    _put: Callable[[Message | AutomationEvent], object]
    """The function that queues a message or an automation event for the Control Loop."""

    def __init__(
        self,
        automations: Automations,
        scheduler: Scheduler,
        output_control: OutputControl,
        put: Callable[[Message | AutomationEvent], object],
        logger: logging.Logger,
    ) -> None:
        """Set up the decision regarding the toggle timers automations.

        Args:
            automations (Automations): The automations.
            scheduler (Scheduler): The scheduler.
            output_control (OutputControl): The control of the outputs.
            put (Callable[[Message | AutomationEvent], object]): The function that queues a message or an automation
                event for the Control Loop.
            logger (logging.Logger): The logger to write to.

        """
        self._automations = automations
        self._scheduler = scheduler
        self._output_control = output_control
        self._logger = logger

        self._put = put

    @override
    def decide(self, readings: Mapping[int, Reading], conditions_state: ConditionsState) -> None:
        """Start the toggle timers whose conditions are satisfied, and stop the running ones whose aren't."""
        for automation in self._automations.get_all(ToggleTimerAutomation):
            satisfied = automation.conditions_satisfied(conditions_state)
            if satisfied and not automation.is_running:
                self._switch_and_schedule_next(automation, turn_on=True)
            elif automation.is_running and not satisfied:
                self._stop_and_turn_off(automation)

    @override
    def react(self, event: AutomationEvent, conditions_state: ConditionsState) -> None:
        pass

    def switch_output(self, message: SwitchToggleTimerOutput, conditions_state: ConditionsState) -> None:
        """Turn the output of a toggle timer on or off.

        Args:
            message (SwitchToggleTimerOutput): The toggle timer automation as it was when the time started, and whether
                to turn its output on or off.
            conditions_state (ConditionsState): The current state of the things that the automation conditions check.

        """
        index_id = message.automation.config.index_id

        try:
            automation = self._automations.get(index_id, ToggleTimerAutomation)
        except AutomationError as error:
            self._logger.debug("Can't toggle the output of automation %s: %s", index_id, error)
            return

        if automation is not message.automation:
            self._logger.debug("Can't toggle the output of automation %s: its settings changed", index_id)
            return

        if not automation.enabled:
            automation.stop()
            self._logger.info("Automation %s stopped controlling output %s", index_id, automation.config.output)
        elif not automation.conditions_satisfied(conditions_state):
            self._stop_and_turn_off(automation)
        else:
            self._switch_and_schedule_next(automation, turn_on=message.turn_on)

    def _switch_and_schedule_next(self, automation: ToggleTimerAutomation, *, turn_on: bool) -> None:
        config = automation.config
        index_id = config.index_id
        state = OutputSetState.ON if turn_on else OutputSetState.OFF

        origin = f"automation {index_id}"
        if not self._output_control.control(config.output, state, config, origin, log_level=logging.DEBUG):
            self._logger.debug("Automation %s can't control output %s", index_id, config.output)
            automation.stop()
            return

        if not automation.is_running:
            self._logger.info("Automation %s started controlling output %s", index_id, config.output)
        automation.start()
        self._scheduler.schedule(
            f"automation:{index_id}:toggle",
            config.toggle_timer_on if turn_on else config.toggle_timer_off,
            partial(self._put, SwitchToggleTimerOutput(automation, turn_on=not turn_on)),
        )

    def _stop_and_turn_off(self, automation: ToggleTimerAutomation) -> None:
        index_id = automation.config.index_id
        output_id = automation.config.output

        if automation.is_running:
            self._logger.info("Automation %s stopped controlling output %s: turning it off", index_id, output_id)

        self._scheduler.cancel(f"automation:{index_id}:toggle")
        self._output_control.control(
            output_id,
            OutputSetState.OFF,
            automation.config,
            f"automation {index_id}",
            log_level=logging.DEBUG,
        )
        automation.stop()
