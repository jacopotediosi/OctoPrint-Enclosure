from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

from octoprint.events import Events

from .actions import ActionError, GcodeAction, GcodeConfig, PrinterAction
from .automations import (
    AutomationError,
    AutomationEvent,
    FilamentAutomation,
    GpioEdgeEvent,
    GpioInputTrigger,
    OctoprintEvent,
    OutputControlReaction,
    OutputSetState,
    PwmTemperatureLinkedAutomation,
    ReadingsEvent,
    RuleAutomation,
    RunActionReaction,
    TemperatureTrigger,
    ToggleTimerAutomation,
)
from .inputs import GpioInputError
from .notifications import NotificationType
from .outputs import (
    Output,
    OutputError,
    OutputSetpointConfig,
    PwmOutput,
    PwmSetpoint,
    Thermostat,
    ThermostatOutput,
    ThermostatStatus,
)

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Mapping

    from octoprint.printer import PrinterInterface

    from .actions import Action, Actions
    from .automations import Automations, Reaction
    from .core import Frontend, Scheduler, Settings
    from .inputs import GpioInputs, Reading, SensorPoller
    from .notifications import Notifications
    from .output_executor import OutputExecutor
    from .outputs import Outputs

TICK_INTERVAL_SECONDS = 10
"""The seconds between two ticks, at which the loop takes the decisions again on everything."""

##########
### Messages
##########


class _Message:
    """A message to the Control Loop thread."""


@dataclass(frozen=True)
class _Stop(_Message):
    """The Control Loop stops."""


@dataclass(frozen=True)
class _NewReading(_Message):
    """A sensor has a new reading."""

    index_id: int
    """The id of the input of the sensor."""


@dataclass(frozen=True)
class _Tick(_Message):
    """Time to take the decisions again."""


@dataclass(frozen=True)
class _SettingsLoaded(_Message):
    """New settings were loaded."""


@dataclass(frozen=True)
class _ThermostatTargetChanged(_Message):
    """The target of a thermostat changed."""

    index_id: int
    """The id of the thermostat."""

    target: float
    """The new target temperature or humidity, or 0 if the thermostat turned off."""


@dataclass(frozen=True)
class _WaitForTemperature(_Message):
    """A print waits for a thermostat to reach its target."""

    index_id: int
    """The id of the thermostat."""


@dataclass(frozen=True)
class _UpdateUiTargets(_Message):
    """The UI asks for the targets of the thermostats."""


@dataclass(frozen=True)
class _RunRule(_Message):
    """The delay of a rule is over."""

    rule: RuleAutomation
    """The rule as it was when its delay started."""

    notify: Callable[[Reaction, Action | None], None] | None
    """How the rule notifies each reaction done, or None if it doesn't notify."""


@dataclass(frozen=True)
class _ToggleOutput(_Message):
    """The on/off time of an output controlled by a toggle timer automation is over."""

    automation: ToggleTimerAutomation
    """The toggle timer automation as it was when the time started."""

    turn_on: bool
    """Whether to turn the output on now, or off."""


class ControlLoop:
    """Takes the decisions of the plugin on a thread of its own: what the outputs do, and when the automations act.

    This is the only place that decides whether an output is on or off, and the automations can also act on the
    printer. Every decision runs on this one thread, one at a time and always in the same order, so when several
    automations want the same output, who wins never depends on timing.
    """

    _gpio_inputs: GpioInputs
    _sensor_poller: SensorPoller
    _outputs: Outputs
    _actions: Actions
    _automations: Automations
    _output_executor: OutputExecutor
    _scheduler: Scheduler
    _notifications: Notifications
    _printer: PrinterInterface
    _frontend: Frontend
    _settings: Settings
    _logger: logging.Logger

    _thermostats: dict[int, Thermostat]
    """The thermostats, by the id of their output."""

    _print_job_running: bool
    """Whether a print job is running."""

    _waiting_temperature: set[int]
    """The ids of the thermostats a paused print waits for, until they reach their target."""

    _queue: queue.Queue[_Message | AutomationEvent]
    """The messages and the automation events to handle, in order."""

    _thread: threading.Thread

    def __init__(
        self,
        gpio_inputs: GpioInputs,
        sensor_poller: SensorPoller,
        outputs: Outputs,
        actions: Actions,
        automations: Automations,
        output_executor: OutputExecutor,
        scheduler: Scheduler,
        notifications: Notifications,
        printer: PrinterInterface,
        frontend: Frontend,
        settings: Settings,
        logger: logging.Logger,
    ) -> None:
        """Set up the loop, with its thread ready to start.

        Args:
            gpio_inputs (GpioInputs): The GPIO inputs.
            sensor_poller (SensorPoller): The poller of the temperature sensors.
            outputs (Outputs): The outputs.
            actions (Actions): The actions.
            automations (Automations): The automations.
            output_executor (OutputExecutor): The executor of the commands to the outputs.
            scheduler (Scheduler): The scheduler.
            notifications (Notifications): The notifications.
            printer (PrinterInterface): The OctoPrint printer interface.
            frontend (Frontend): The frontend handler.
            settings (Settings): The plugin settings.
            logger (logging.Logger): The logger to write to.

        """
        self._gpio_inputs = gpio_inputs
        self._sensor_poller = sensor_poller
        self._outputs = outputs
        self._actions = actions
        self._automations = automations
        self._output_executor = output_executor
        self._scheduler = scheduler
        self._notifications = notifications
        self._printer = printer
        self._frontend = frontend
        self._settings = settings
        self._logger = logger.getChild("ControlLoop")

        self._thermostats = {}
        self._print_job_running = False
        self._waiting_temperature = set()
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="EnclosureControlLoop", daemon=True)

    def start(self) -> None:
        """Start taking decisions, on the Control Loop thread."""
        self._thread.start()

    def stop(self) -> None:
        """Stop taking decisions."""
        if self._thread.is_alive():
            self._put(_Stop())
            self._thread.join()

    def evaluate(self) -> None:
        """Take the decisions again now."""
        self._put(_Tick())

    def evaluate_reading(self, index_id: int) -> None:
        """Take the decisions regarding a new sensor reading.

        Args:
            index_id (int): The id of the input of the sensor.

        """
        self._put(_NewReading(index_id))

    def evaluate_gpio_input_edge(self, input_id: int, level: int) -> None:
        """Take the decisions regarding an edge on a GPIO input.

        Args:
            input_id (int): The id of the input.
            level (int): The level of the input after the edge, 1 if high or 0 if low.

        """
        self._put(GpioEdgeEvent(input_id, level))

    def evaluate_octoprint_event(self, event: str) -> None:
        """Take the decisions regarding an event of OctoPrint.

        Args:
            event (str): The event, as OctoPrint names it.

        """
        self._put(OctoprintEvent(event))

    def evaluate_settings(self) -> None:
        """Take the decisions again after new settings were loaded."""
        self._put(_SettingsLoaded())

    def set_thermostat_target(self, index_id: int, target: float) -> None:
        """Set the target of a thermostat, and take the decisions regarding it.

        Args:
            index_id (int): The id of the thermostat.
            target (float): The target temperature or humidity, or 0 to turn the thermostat off.

        """
        self._put(_ThermostatTargetChanged(index_id, target))

    def get_thermostats(self) -> dict[int, Thermostat]:
        """Get the thermostats.

        Returns:
            dict[int, Thermostat]: The thermostats, by the id of their output.

        """
        return dict(self._thermostats)

    def wait_for_temperature(self, index_id: int) -> None:
        """Resume the paused print once a thermostat reaches its target.

        Args:
            index_id (int): The id of the thermostat the print waits for.

        """
        self._put(_WaitForTemperature(index_id))

    def update_ui_targets(self) -> None:
        """Update the targets of the thermostats in the UI."""
        self._put(_UpdateUiTargets())

    def _put(self, message: _Message | AutomationEvent) -> None:
        self._queue.put(message)

    def _run(self) -> None:
        try:
            self._start_deciding()
        except Exception:
            self._logger.exception("Error starting to decide")

        next_tick = time.monotonic() + TICK_INTERVAL_SECONDS
        while True:
            # Wait for a message, or for the tick if it comes first
            timeout = next_tick - time.monotonic()
            if timeout <= 0:
                message: _Message | AutomationEvent = _Tick()
                next_tick = time.monotonic() + TICK_INTERVAL_SECONDS
            else:
                try:
                    message = self._queue.get(timeout=timeout)
                except queue.Empty:
                    continue

            # Stop the loop if the message is a stop
            if isinstance(message, _Stop):
                return

            # Handle the message
            try:
                self._handle(message)
            except Exception:
                self._logger.exception("Error handling %s", message)

    def _handle(self, message: _Message | AutomationEvent) -> None:
        if isinstance(message, _Tick):
            self._decide_continuous()
        elif isinstance(message, _NewReading):
            readings = self._sensor_poller.get_readings()
            self._decide_thermostats(readings, message.index_id)
            self._decide_temperature_rules(ReadingsEvent(readings, message.index_id))
            self._decide_pwm_linked_temperature(readings, message.index_id)
        elif isinstance(message, GpioEdgeEvent):
            self._decide_gpio_input_edge(message)
        elif isinstance(message, OctoprintEvent):
            self._decide_octoprint_event(message)
        elif isinstance(message, _SettingsLoaded):
            self._load_thermostats()
            self._frontend.update_targets(self.get_thermostats())

            # While printing every filament automation has to watch, the new ones too
            if self._printer.is_printing():
                self._start_filament_detection()

            self._decide_continuous()
        elif isinstance(message, _ThermostatTargetChanged):
            thermostat = self._thermostats.get(message.index_id)
            if thermostat is None:
                self._logger.debug("Can't set the target of output %s: it isn't a thermostat", message.index_id)
            else:
                thermostat.set_target(message.target)
                self._frontend.update_targets(self.get_thermostats())
                self._decide_thermostats(self._sensor_poller.get_readings(), None)
        elif isinstance(message, _WaitForTemperature):
            self._waiting_temperature.add(message.index_id)
            self._decide_thermostats(self._sensor_poller.get_readings(), None)
        elif isinstance(message, _UpdateUiTargets):
            self._frontend.update_targets(self.get_thermostats())
        elif isinstance(message, _RunRule):
            index_id = message.rule.config.index_id
            try:
                rule = self._automations.get(index_id, RuleAutomation)
            except AutomationError as error:
                self._logger.debug("Can't run automation %s after its delay: %s", index_id, error)
            else:
                if rule is message.rule:
                    self._run_rule(rule, message.notify)
                else:
                    self._logger.debug("Can't run automation %s after its delay: its settings changed", index_id)
        elif isinstance(message, _ToggleOutput):
            index_id = message.automation.config.index_id
            try:
                automation = self._automations.get(index_id, ToggleTimerAutomation)
            except AutomationError as error:
                self._logger.debug("Can't toggle the output of automation %s: %s", index_id, error)
            else:
                if automation is not message.automation:
                    self._logger.debug("Can't toggle the output of automation %s: its settings changed", index_id)
                elif not automation.enabled:
                    self._logger.debug("Automation %s is disabled", index_id)
                    automation.stop()
                elif not automation.conditions_satisfied(printing=self._print_job_running):
                    self._stop_toggle_timer(automation)
                else:
                    self._toggle_output(automation, turn_on=message.turn_on)

    def _start_deciding(self) -> None:
        self._load_thermostats()
        self._print_job_running = bool(self._printer.is_printing() or self._printer.is_paused())
        self._decide_gpio_input_levels()
        self._decide_continuous()

    def _load_thermostats(self) -> None:
        thermostats: dict[int, Thermostat] = {}

        for output in self._outputs.get_all(ThermostatOutput):
            # Keep the thermostat of an output the settings didn't change, with its target
            index_id = output.config.index_id
            thermostat = self._thermostats.get(index_id)
            if thermostat is None or thermostat.config != output.config:
                thermostat = Thermostat(output.config)
            thermostats[index_id] = thermostat

        self._thermostats = thermostats

    def _decide_gpio_input_levels(self) -> None:
        try:
            for rule in self._automations.get_all(RuleAutomation):
                # Get the trigger and the reactions that control an output
                trigger = rule.trigger
                reactions = [reaction for reaction in rule.reactions if isinstance(reaction, OutputControlReaction)]

                # Skip the automation rules which don't react to gpio inputs by controlling an output, and the delayed
                # ones, that act some time after an edge, not on the level
                if not isinstance(trigger, GpioInputTrigger) or not reactions or rule.config.delay or rule.config.at:
                    continue

                # Get the trigger input id
                input_id = trigger.config.input

                # Get the input level
                try:
                    level = self._gpio_inputs.get(input_id).read_pin_level()
                except GpioInputError as error:
                    self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                    continue

                # React if the input level matches the trigger and the conditions of the rule are satisfied
                if trigger.matches(GpioEdgeEvent(input_id, level)) and rule.conditions_satisfied(
                    printing=self._print_job_running,
                ):
                    for reaction in reactions:
                        config = reaction.config
                        self._control_output(config.controlled_io, config.controlled_io_set_state, config)
        except Exception:
            self._logger.exception("Error applying the levels of the GPIO inputs")

    def _decide_continuous(self) -> None:
        readings = self._sensor_poller.get_readings()

        self._decide_thermostats(readings, None)
        self._decide_pwm_linked_temperature(readings, None)
        self._decide_toggle_timers()

    def _decide_thermostats(self, readings: Mapping[int, Reading], sensor_id: int | None) -> None:
        try:
            for index_id, thermostat in self._thermostats.items():
                # With a new reading, decide only the thermostats linked to its sensor
                if sensor_id is not None and thermostat.config.linked_temp_sensor != sensor_id:
                    continue

                # Get the reading of the linked sensor
                linked_reading = readings.get(thermostat.config.linked_temp_sensor)
                temperature = None if linked_reading is None else linked_reading.temperature
                humidity = None if linked_reading is None else linked_reading.humidity

                # Turn a heater off above its maximum temperature
                if thermostat.is_above_max_temp(temperature):
                    self._logger.warning("Thermostat %s reached its maximum temperature: turning it off", index_id)
                    thermostat.set_target(0.0)
                    self._frontend.update_targets(self.get_thermostats())

                # Decide whether the device has to be on, and switch it
                should_be_on = thermostat.decide(temperature, humidity)
                self._output_executor.switch_thermostat(index_id, on=should_be_on)

            # Resume the print paused by ENC W1 once every thermostat it waits for is at its target
            self._decide_waiting_print()
        except Exception:
            self._logger.exception("Error handling the thermostats")

    def _decide_waiting_print(self) -> None:
        # Avoid resuming prints if they were not paused to wait for temperatures
        if not self._waiting_temperature:
            return

        for index_id in list(self._waiting_temperature):
            # Get the thermostat we are waiting for
            thermostat = self._thermostats.get(index_id)
            if thermostat is None:
                self._waiting_temperature.discard(index_id)
                continue

            # Check if the thermostat has not reached the temperature yet
            if thermostat.status is not ThermostatStatus.IDLE:
                return

        # Resume the print
        if self._printer.is_paused():
            self._waiting_temperature.clear()
            self._printer.resume_print()

    def _decide_temperature_rules(self, event: ReadingsEvent) -> None:
        for automation in self._automations.get_triggered(event):
            if isinstance(automation, RuleAutomation) and isinstance(automation.trigger, TemperatureTrigger):
                self._react_to_temperature(automation, automation.trigger.config.alarm_set_temp)

    def _react_to_temperature(self, rule: RuleAutomation, threshold: float) -> None:
        temperature_unit = self._settings.temperature_unit
        cause = f"enclosure temperature exceed {temperature_unit.from_celsius(threshold):g} {temperature_unit.symbol}"

        def notify(reaction: Reaction, action: Action | None) -> None:
            if isinstance(reaction, OutputControlReaction) or isinstance(action, GcodeAction):
                self._notifications.send(NotificationType.TEMPERATURE_ACTION, f"Temperature action: {cause}")
            elif isinstance(action, PrinterAction):
                self._notifications.send(
                    NotificationType.PRINTER_ACTION,
                    f"Printer action: {action.config.printer_action.value} caused by {cause}",
                )

        self._react(rule, notify)

    def _react(self, rule: RuleAutomation, notify: Callable[[Reaction, Action | None], None] | None) -> None:
        delay_seconds = rule.config.delay_seconds()
        if delay_seconds > 0:
            self._scheduler.schedule(
                f"automation:{rule.config.index_id}:delay",
                delay_seconds,
                lambda: self._put(_RunRule(rule, notify)),
            )
        else:
            self._run_rule(rule, notify)

    def _run_rule(self, rule: RuleAutomation, notify: Callable[[Reaction, Action | None], None] | None) -> None:
        if not rule.enabled:
            self._logger.debug("Automation %s is disabled", rule.config.index_id)
            return

        if not rule.conditions_satisfied(printing=self._print_job_running):
            self._logger.debug("The conditions of automation %s aren't satisfied", rule.config.index_id)
            return

        for reaction in rule.reactions:
            try:
                if isinstance(reaction, OutputControlReaction):
                    config = reaction.config
                    controlled = self._control_output(config.controlled_io, config.controlled_io_set_state, config)
                    if controlled and notify is not None:
                        notify(reaction, None)
                elif isinstance(reaction, RunActionReaction):
                    try:
                        action = self._actions.run(reaction.config.action)
                    except ActionError as error:
                        self._logger.debug("Can't run action %s: %s", reaction.config.action, error)
                    else:
                        if notify is not None:
                            notify(reaction, action)
            except Exception:
                self._logger.exception(
                    "Error handling the reaction %s of the rule on %s",
                    reaction.config,
                    rule.trigger.config,
                )

    def _decide_pwm_linked_temperature(self, readings: Mapping[int, Reading], sensor_id: int | None) -> None:
        try:
            for automation in self._automations.get_all(PwmTemperatureLinkedAutomation):
                # A curve drives the PWM only while its conditions are satisfied
                if not automation.conditions_satisfied(printing=self._print_job_running):
                    if automation.is_running:
                        self._reset_pwm_linked_temperature(automation)
                    continue

                # With a new reading, decide only the curves linked to its sensor, and the ones that start now
                if (
                    sensor_id is not None
                    and automation.config.linked_temp_sensor != sensor_id
                    and automation.is_running
                ):
                    continue

                # Get the automation output
                output_id = automation.config.output

                # Get the reading of the linked sensor
                linked_reading = readings.get(automation.config.linked_temp_sensor)
                temperature = None if linked_reading is None else linked_reading.temperature

                # Calculate the new duty cycle
                calculated_duty = automation.get_duty_cycle(temperature)

                # Write the new duty cycle to the output
                self._output_executor.turn_on(output_id, PwmSetpoint(calculated_duty))
                automation.start()
        except Exception:
            self._logger.exception("Error handling temperature linked PWM outputs")

    def _reset_pwm_linked_temperature(self, automation: PwmTemperatureLinkedAutomation) -> None:
        output_id = automation.config.output
        try:
            default_duty_cycle = self._outputs.get(output_id, PwmOutput).config.default_duty_cycle
        except OutputError as error:
            self._logger.debug("Can't reset the duty cycle of output %s: %s", output_id, error)
        else:
            self._output_executor.turn_on(output_id, PwmSetpoint(default_duty_cycle))
        automation.stop()

    def _decide_gpio_input_edge(self, event: GpioEdgeEvent) -> None:
        try:
            input_label = self._gpio_inputs.get(event.input_id).config.label
        except GpioInputError:
            input_label = ""
        for automation in self._automations.get_triggered(event):
            if isinstance(automation, RuleAutomation):
                self._react_to_gpio_edge(automation, input_label)
            elif isinstance(automation, FilamentAutomation):
                self._detect_filament_end(automation, event.input_id, input_label)

    def _react_to_gpio_edge(self, rule: RuleAutomation, input_label: str) -> None:
        def notify(reaction: Reaction, action: Action | None) -> None:
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

        self._react(rule, notify)

    def _detect_filament_end(self, automation: FilamentAutomation, input_id: int, input_label: str) -> None:
        try:
            if automation.detect_end():
                gcode_config = GcodeConfig(self._settings.filament_sensor_gcode)
                gcode_logger = self._logger.getChild("GcodeAction")
                GcodeAction(gcode_config, self._printer, self._frontend, gcode_logger).run()
                self._notifications.send(
                    NotificationType.FILAMENT_CHANGE,
                    f"Filament change action caused by sensor: {input_label}",
                )
        except Exception:
            self._logger.exception("Error handling filament detection of input %s", input_id)

    def _decide_octoprint_event(self, event: OctoprintEvent) -> None:
        if event.name == Events.PRINT_STARTED:
            self._print_job_running = True
            self._start_filament_detection()
        elif event.name == Events.PRINT_RESUMED:
            self._waiting_temperature.clear()
            self._start_filament_detection()
        elif event.name == Events.PRINT_PAUSED:
            self._decide_waiting_print()
        elif event.name in (Events.PRINT_DONE, Events.PRINT_CANCELLED, Events.PRINT_FAILED):
            self._print_job_running = False
            self._waiting_temperature.clear()
            self._stop_filament_detection()

        # The automation conditions depend on the print job: decide the continuous automations again when it changes
        if event.name in (
            Events.PRINT_STARTED,
            Events.PRINT_RESUMED,
            Events.PRINT_PAUSED,
            Events.PRINT_DONE,
            Events.PRINT_CANCELLED,
            Events.PRINT_FAILED,
        ):
            self._decide_continuous()

        for automation in self._automations.get_triggered(event):
            if isinstance(automation, RuleAutomation):
                self._react(automation, None)

    def _start_filament_detection(self) -> None:
        try:
            # The disabled sensors too: they follow the print like the others, and detect as soon as they are enabled
            for automation in self._automations.get_all(FilamentAutomation, include_disabled=True):
                automation.disarm()

                input_id = automation.trigger.config.input

                try:
                    level = self._gpio_inputs.get(input_id).read_pin_level()
                except GpioInputError as error:
                    self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                    continue

                if automation.enabled and automation.is_filament_missing(level):
                    self._printer.pause_print()
                    self._logger.info("Started printing with no filament.")
                else:
                    automation.arm()
        except Exception:
            self._logger.exception("Error starting filament detection")

    def _stop_filament_detection(self) -> None:
        for automation in self._automations.get_all(FilamentAutomation, include_disabled=True):
            automation.disarm()

    def _decide_toggle_timers(self) -> None:
        try:
            for automation in self._automations.get_all(ToggleTimerAutomation):
                satisfied = automation.conditions_satisfied(printing=self._print_job_running)
                if satisfied and not automation.is_running:
                    self._toggle_output(automation, turn_on=True)
                elif automation.is_running and not satisfied:
                    self._stop_toggle_timer(automation)
        except Exception:
            self._logger.exception("Error handling the toggle timers")

    def _toggle_output(self, automation: ToggleTimerAutomation, *, turn_on: bool) -> None:
        config = automation.config
        index_id = config.index_id
        state = OutputSetState.ON if turn_on else OutputSetState.OFF
        if not self._control_output(config.output, state, config):
            self._logger.debug("Can't toggle output %s of automation %s: it isn't set up", config.output, index_id)
            automation.stop()
            return

        automation.start()
        self._scheduler.schedule(
            f"automation:{index_id}:toggle",
            config.toggle_timer_on if turn_on else config.toggle_timer_off,
            lambda: self._put(_ToggleOutput(automation, turn_on=not turn_on)),
        )

    def _stop_toggle_timer(self, automation: ToggleTimerAutomation) -> None:
        index_id = automation.config.index_id
        self._scheduler.cancel(f"automation:{index_id}:toggle")
        self._control_output(automation.config.output, OutputSetState.OFF, automation.config)
        automation.stop()

    def _control_output(self, index_id: int, state: OutputSetState, setpoint_config: OutputSetpointConfig) -> bool:
        try:
            output = self._outputs.get(index_id, Output)
        except OutputError:
            return False
        setpoint_class = output.setpoint_class
        setpoint = setpoint_class(
            **{field.name: getattr(setpoint_config, field.name) for field in fields(setpoint_class)},
        )

        if isinstance(output, ThermostatOutput):
            thermostat = self._thermostats.get(index_id)
            if thermostat is None:
                return False
            if state is OutputSetState.ON or (state is OutputSetState.TOGGLE and not thermostat.is_on()):
                thermostat.turn_on(setpoint)
            else:
                thermostat.turn_off()
            self._frontend.update_targets(self.get_thermostats())
            self._decide_thermostats(self._sensor_poller.get_readings(), None)
        elif state is OutputSetState.ON:
            self._output_executor.turn_on(index_id, setpoint)
        elif state is OutputSetState.OFF:
            self._output_executor.turn_off(index_id)
        else:
            self._output_executor.toggle(index_id, setpoint)
        return True
