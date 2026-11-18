from __future__ import annotations

import contextlib
from functools import partial
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.actions import ActionError, GcodeAction, PrinterAction
from octoprint_enclosure.automations import (
    AutomationError,
    GpioEdgeEvent,
    GpioInputTrigger,
    OctoprintEvent,
    OutputControlReaction,
    OutputSetState,
    ReadingEvent,
    RuleAutomation,
    RunActionReaction,
    TemperatureTrigger,
)
from octoprint_enclosure.engine.control_loop.messages import RunAutomationRuleReactions
from octoprint_enclosure.inputs import GpioInputError
from octoprint_enclosure.notifications import NotificationType

from .base import Decision

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Mapping

    from octoprint_enclosure.actions import Action, Actions
    from octoprint_enclosure.automations import AutomationEvent, Automations, ConditionsState, Reaction
    from octoprint_enclosure.engine.control_loop.messages import Message
    from octoprint_enclosure.engine.scheduler import Scheduler
    from octoprint_enclosure.inputs import GpioInputs, Reading, Sensors
    from octoprint_enclosure.notifications import Notifications
    from octoprint_enclosure.settings import Settings

    from .output_control import OutputControl


class AutomationRuleDecision(Decision):
    """The decision regarding the automation rules."""

    _sensors: Sensors
    _gpio_inputs: GpioInputs
    _actions: Actions
    _automations: Automations
    _scheduler: Scheduler
    _notifications: Notifications
    _settings: Settings
    _output_control: OutputControl
    _logger: logging.Logger

    _put: Callable[[Message | AutomationEvent], object]
    """The function that queues a message or an automation event for the Control Loop."""

    def __init__(
        self,
        sensors: Sensors,
        gpio_inputs: GpioInputs,
        actions: Actions,
        automations: Automations,
        scheduler: Scheduler,
        notifications: Notifications,
        settings: Settings,
        output_control: OutputControl,
        put: Callable[[Message | AutomationEvent], object],
        logger: logging.Logger,
    ) -> None:
        """Set up the decision regarding the automation rules.

        Args:
            sensors (Sensors): The temperature sensors.
            gpio_inputs (GpioInputs): The GPIO inputs.
            actions (Actions): The actions.
            automations (Automations): The automations.
            scheduler (Scheduler): The scheduler.
            notifications (Notifications): The notifications.
            settings (Settings): The plugin settings.
            output_control (OutputControl): The control of the outputs.
            put (Callable[[Message | AutomationEvent], object]): The function that queues a message or an automation
                event for the Control Loop.
            logger (logging.Logger): The logger to write to.

        """
        self._sensors = sensors
        self._gpio_inputs = gpio_inputs
        self._actions = actions
        self._automations = automations
        self._scheduler = scheduler
        self._notifications = notifications
        self._settings = settings
        self._output_control = output_control
        self._logger = logger

        self._put = put

    @override
    def decide(self, readings: Mapping[int, Reading], conditions_state: ConditionsState) -> None:
        pass

    @override
    def react(self, event: AutomationEvent, conditions_state: ConditionsState) -> None:
        """React to an automation event: run the rules that it starts, now or after their delay."""
        if isinstance(event, GpioEdgeEvent):
            cause = f"GPIO input {event.input_id} going {'high' if event.level else 'low'}"
        elif isinstance(event, ReadingEvent):
            cause = f"sensor {event.index_id} reading {event.reading}"
        elif isinstance(event, OctoprintEvent):
            cause = f"OctoPrint event {event.name}"
        else:
            cause = str(event)

        for rule in self._automations.get_triggered(event, RuleAutomation):
            index_id = rule.config.index_id
            delay_seconds = rule.config.delay_seconds()

            if delay_seconds > 0:
                when = f"at {rule.config.at}" if rule.config.at else f"in {delay_seconds:g} s"
                self._logger.info("Automation %s triggered by %s: runs %s", index_id, cause, when)
                self._scheduler.schedule(
                    f"automation:{index_id}:delay",
                    delay_seconds,
                    partial(self._put, RunAutomationRuleReactions(rule, event)),
                )
            elif rule.conditions_satisfied(conditions_state):
                self._logger.info("Automation %s triggered by %s", index_id, cause)
                self._run_reactions_now(rule, event)
            else:
                self._logger.debug("The conditions of automation %s aren't satisfied", index_id)

    def apply_gpio_input_levels(self, conditions_state: ConditionsState) -> None:
        """Control the outputs of the rules on a GPIO input, from the level each input has now.

        Args:
            conditions_state (ConditionsState): The current state of the things that the automation conditions check.

        """
        for rule in self._automations.get_all(RuleAutomation):
            # Skip the rules that are not on a GPIO input, and the delayed ones, that act some time after an edge
            trigger = rule.trigger
            if not isinstance(trigger, GpioInputTrigger) or rule.config.delay or rule.config.at:
                continue

            # Get the trigger input id
            input_id = trigger.config.input

            # Get the input level
            try:
                level = self._gpio_inputs.get(input_id).read_pin_level()
            except GpioInputError as error:
                self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                continue
            if level is None:
                continue

            # React if the input level matches the trigger and the conditions of the rule are satisfied
            level_matches = trigger.matches(GpioEdgeEvent(input_id, level))
            if level_matches and rule.conditions_satisfied(conditions_state):
                for reaction in rule.reactions:
                    if isinstance(reaction, OutputControlReaction):
                        config = reaction.config

                        # A toggle is skipped: the level of an input doesn't tell that the input changed
                        if config.controlled_io_set_state is not OutputSetState.TOGGLE:
                            self._output_control.control(
                                config.controlled_io,
                                config.controlled_io_set_state,
                                config,
                                f"automation {rule.config.index_id}",
                            )

    def run_reactions(self, message: RunAutomationRuleReactions, conditions_state: ConditionsState) -> None:
        """Run now the reactions of a rule whose delay is over, unless the rule changed meanwhile.

        Args:
            message (RunAutomationRuleReactions): The rule as it was when its delay started, with what started it.
            conditions_state (ConditionsState): The current state of the things that the automation conditions check.

        """
        index_id = message.rule.config.index_id

        try:
            rule = self._automations.get(index_id, RuleAutomation)
        except AutomationError as error:
            self._logger.debug("Can't run automation %s after its delay: %s", index_id, error)
            return

        if rule is not message.rule:
            self._logger.debug("Can't run automation %s after its delay: its settings changed", index_id)
            return

        if not rule.enabled:
            self._logger.debug("Automation %s is disabled", index_id)
            return

        if not rule.conditions_satisfied(conditions_state):
            self._logger.debug("The conditions of automation %s aren't satisfied", index_id)
            return

        self._run_reactions_now(rule, message.event)

    def notify_sensor_failure(self, sensor_id: int) -> None:
        """Send a notification that a sensor can't be read, if a temperature rule reads it.

        Args:
            sensor_id (int): The id of the input of the sensor.

        """
        read_by_a_rule = any(
            isinstance(rule.trigger, TemperatureTrigger) and rule.trigger.config.linked_temp_sensor == sensor_id
            for rule in self._automations.get_all(RuleAutomation)
        )
        if not read_by_a_rule:
            return

        with contextlib.suppress(LookupError):
            label = self._sensors.get(sensor_id).config.label
            self._notifications.send(
                NotificationType.TEMPERATURE_ACTION,
                f"Temperature alarm: sensor {label} can't be read",
            )

    def _run_reactions_now(self, rule: RuleAutomation, event: AutomationEvent) -> None:
        for reaction in rule.reactions:
            try:
                if isinstance(reaction, OutputControlReaction):
                    config = reaction.config
                    controlled = self._output_control.control(
                        config.controlled_io,
                        config.controlled_io_set_state,
                        config,
                        f"automation {rule.config.index_id}",
                    )
                    if controlled:
                        self._notify(rule, event, reaction, None)
                    else:
                        self._logger.debug(
                            "Automation %s can't control output %s",
                            rule.config.index_id,
                            config.controlled_io,
                        )
                elif isinstance(reaction, RunActionReaction):
                    try:
                        action = self._actions.run(reaction.config.action)
                    except ActionError as error:
                        self._logger.warning(
                            "Automation %s can't run action %s: %s",
                            rule.config.index_id,
                            reaction.config.action,
                            error,
                        )
                    else:
                        self._notify(rule, event, reaction, action)
            except Exception:
                self._logger.exception(
                    "Error running the reaction %s of automation %s",
                    reaction.config,
                    rule.config.index_id,
                )

    def _notify(self, rule: RuleAutomation, event: AutomationEvent, reaction: Reaction, action: Action | None) -> None:
        trigger = rule.trigger

        if isinstance(event, ReadingEvent) and isinstance(trigger, TemperatureTrigger):
            temperature_unit = self._settings.temperature_unit
            threshold = temperature_unit.from_celsius(trigger.config.alarm_set_temp)
            cause = f"enclosure temperature exceed {threshold:g} {temperature_unit.symbol}"

            if isinstance(reaction, OutputControlReaction) or isinstance(action, GcodeAction):
                self._notifications.send(NotificationType.TEMPERATURE_ACTION, f"Temperature action: {cause}")
            elif isinstance(action, PrinterAction):
                self._notifications.send(
                    NotificationType.PRINTER_ACTION,
                    f"Printer action: {action.config.printer_action.value} caused by {cause}",
                )
        elif isinstance(event, GpioEdgeEvent):
            try:
                input_label = self._gpio_inputs.get(event.input_id).config.label
            except GpioInputError:
                input_label = ""

            if isinstance(reaction, OutputControlReaction):
                config = reaction.config
                self._notifications.send(
                    NotificationType.GPIO_ACTION,
                    f"GPIO control action caused by input {input_label}. "
                    f"Setting GPIO{config.controlled_io} to: {config.controlled_io_set_state.value}",
                )
            elif isinstance(action, GcodeAction):
                self._notifications.send(
                    NotificationType.GPIO_ACTION,
                    f"GPIO control action caused by input {input_label}. Sending GCODE command",
                )
            elif isinstance(action, PrinterAction):
                self._notifications.send(
                    NotificationType.PRINTER_ACTION,
                    f"Printer action: {action.config.printer_action.value} caused by input: {input_label}",
                )
