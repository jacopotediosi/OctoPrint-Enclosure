from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint.events import Events

from .actions import Action, ActionError, GcodeAction, GcodeConfig, PrinterAction
from .automations import (
    FilamentAutomation,
    GpioInputTrigger,
    OutputControlReaction,
    PwmTemperatureLinkedAutomation,
    RuleAutomation,
    RunActionReaction,
    StopTempHumControlReaction,
    TemperatureTrigger,
)
from .inputs import GpioInputError
from .notifications import NotificationType
from .outputs import Output, OutputError, PwmOutput, RegularOutput, TempHumControlOutput, TempHumControlStatus
from .utils import to_int

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterable

    from octoprint.printer import PrinterInterface

    from .actions import Actions
    from .automations import Automations
    from .core import Frontend, Settings
    from .inputs import GpioInputs
    from .notifications import Notifications
    from .outputs import Outputs, RegularSetState

TICK_INTERVAL_SECONDS = 10
"""The seconds between two ticks, at which the loop takes the decisions again on everything."""

_PRINT_JOB_EVENTS = frozenset(
    {
        Events.PRINT_STARTED,
        Events.PRINT_RESUMED,
        Events.PRINT_PAUSED,
        Events.PRINT_DONE,
        Events.PRINT_CANCELLED,
        Events.PRINT_FAILED,
    },
)
"""The OctoPrint events of the print job."""


##########
### Events
##########


class _Event:
    """A Control Loop event."""


@dataclass(frozen=True)
class _Start(_Event):
    """The Control Loop starts."""


@dataclass(frozen=True)
class _Stop(_Event):
    """The Control Loop stops."""


@dataclass(frozen=True)
class _NewReading(_Event):
    """A sensor has a new reading."""

    index_id: int
    """The id of the input of the sensor."""


@dataclass(frozen=True)
class _Tick(_Event):
    """Time to take the decisions again."""


@dataclass(frozen=True)
class _GpioInputEdge(_Event):
    """A GPIO input changed level."""

    input_id: int
    """The id of the input."""

    level: int
    """The level of the input after the edge, 1 if high or 0 if low."""


@dataclass(frozen=True)
class _PrintJobEvent(_Event):
    """OctoPrint fired an event of the print job."""

    event: str
    """The event, as OctoPrint names it."""


@dataclass(frozen=True)
class _SettingsLoaded(_Event):
    """New settings were loaded."""


@dataclass(frozen=True)
class _WaitForTemperature(_Event):
    """A print waits for a temperature or humidity control to reach its target."""

    index_id: int
    """The id of the control."""


@dataclass(frozen=True)
class _StopTempHumControls(_Event):
    """The temperature and humidity controls with Auto Shutdown on turn off."""


class ControlLoop:
    """Takes the decisions of the plugin on a thread of its own: what the outputs do, and when the automations act.

    This is the only place that decides whether an output is on or off, and the automations can also act on the
    printer. Every decision runs on this one thread, one at a time and always in the same order, so when several
    controls want the same output, who wins never depends on timing.
    """

    _gpio_inputs: GpioInputs
    _outputs: Outputs
    _automations: Automations
    _actions: Actions
    _notifications: Notifications
    _printer: PrinterInterface
    _frontend: Frontend
    _settings: Settings
    _logger: logging.Logger

    _get_sensor_data: Callable[[], list[dict]]
    """The function giving the last reading of each sensor."""

    _switch_output: Callable[[int, RegularSetState], object]
    """The function switching a regular output, with the id of the output and the state to set."""

    _write_pwm: Callable[[int, float], object]
    """The function setting the duty cycle of a PWM output, with the id of the output and the duty cycle."""

    _update_ui: Callable[[], object]
    """The function refreshing the UI."""

    _print_job_running: bool
    """Whether a print job is running."""

    _waiting_temperature: set[int]
    """The ids of the temperature and humidity controls a paused print waits for, until they reach their target."""

    _queue: queue.Queue[_Event]
    """The events to handle, in order."""

    _thread: threading.Thread

    def __init__(
        self,
        gpio_inputs: GpioInputs,
        outputs: Outputs,
        automations: Automations,
        actions: Actions,
        notifications: Notifications,
        printer: PrinterInterface,
        frontend: Frontend,
        settings: Settings,
        logger: logging.Logger,
        *,
        get_sensor_data: Callable[[], list[dict]],
        switch_output: Callable[[int, RegularSetState], object],
        write_pwm: Callable[[int, float], object],
        update_ui: Callable[[], object],
    ) -> None:
        """Set up the loop, with its thread ready to start.

        Args:
            gpio_inputs (GpioInputs): The GPIO inputs.
            outputs (Outputs): The outputs.
            automations (Automations): The automations.
            actions (Actions): The actions.
            notifications (Notifications): The notifications.
            printer (PrinterInterface): The OctoPrint printer interface.
            frontend (Frontend): The frontend handler.
            settings (Settings): The plugin settings.
            logger (logging.Logger): The logger to write to.
            get_sensor_data (Callable[[], list[dict]]): The function giving the last reading of each sensor, as a list
                of dicts with the keys index_id, temperature, humidity and airquality.
            switch_output (Callable[[int, RegularSetState], object]): The function switching a regular output, called
                with the id of the output and the state to set.
            write_pwm (Callable[[int, float], object]): The function setting the duty cycle of a PWM output, called
                with the id of the output and the duty cycle.
            update_ui (Callable[[], object]): The function refreshing the UI.

        """
        self._gpio_inputs = gpio_inputs
        self._outputs = outputs
        self._automations = automations
        self._actions = actions
        self._notifications = notifications
        self._printer = printer
        self._frontend = frontend
        self._settings = settings
        self._logger = logger.getChild("ControlLoop")

        self._get_sensor_data = get_sensor_data
        self._switch_output = switch_output
        self._write_pwm = write_pwm
        self._update_ui = update_ui

        self._print_job_running = False
        self._waiting_temperature = set()
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="EnclosureControlLoop", daemon=True)

    def start(self) -> None:
        """Start taking decisions, on the Control Loop thread."""
        self._put(_Start())
        self._thread.start()

    def stop(self) -> None:
        """Stop taking decisions and turn every output off."""
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
        self._put(_GpioInputEdge(input_id, level))

    def evaluate_octoprint_event(self, event: str) -> None:
        """Take the decisions regarding an event of OctoPrint.

        Args:
            event (str): The OctoPrint event.

        """
        if event in _PRINT_JOB_EVENTS:
            self._put(_PrintJobEvent(event))

    def evaluate_settings(self) -> None:
        """Take the decisions again after new settings were loaded."""
        self._put(_SettingsLoaded())

    def wait_for_temperature(self, index_id: int) -> None:
        """Resume the paused print once a temperature or humidity control reaches its target.

        Args:
            index_id (int): The id of the control the print waits for.

        """
        self._put(_WaitForTemperature(index_id))

    def stop_temp_hum_controls(self) -> None:
        """Turn off the temperature and humidity controls with Auto Shutdown on."""
        self._put(_StopTempHumControls())

    def _put(self, event: _Event) -> None:
        self._queue.put(event)

    def _run(self) -> None:
        next_tick = time.monotonic() + TICK_INTERVAL_SECONDS
        while True:
            # Wait for an event, or for the tick if it comes first
            timeout = next_tick - time.monotonic()
            if timeout <= 0:
                event: _Event = _Tick()
                next_tick = time.monotonic() + TICK_INTERVAL_SECONDS
            else:
                try:
                    event = self._queue.get(timeout=timeout)
                except queue.Empty:
                    continue

            # Handle the event
            try:
                self._handle(event)
            except Exception:
                self._logger.exception("Error handling %s", event)

            # Stop the loop if the event was a stop
            if isinstance(event, _Stop):
                return

    def _handle(self, event: _Event) -> None:
        if isinstance(event, _Start):
            self._print_job_running = bool(self._printer.is_printing() or self._printer.is_paused())
            self._decide_gpio_input_levels()
        elif isinstance(event, _Stop):
            self._turn_off_all_outputs()
        elif isinstance(event, _Tick):
            self._decide_all()
        elif isinstance(event, _NewReading):
            sensor_data = self._get_sensor_data()
            self._decide_temp_hum_controls(sensor_data, event.index_id)
            self._decide_temperature_rules(sensor_data, event.index_id)
            self._decide_pwm_linked_temperature(sensor_data, event.index_id)
        elif isinstance(event, _GpioInputEdge):
            self._decide_gpio_input_edge(event.input_id, event.level)
        elif isinstance(event, _PrintJobEvent):
            self._decide_print_job_event(event.event)
        elif isinstance(event, _SettingsLoaded):
            # While printing every filament automation has to watch: start the ones that don't yet
            if self._printer.is_printing():
                not_armed = [a for a in self._automations.get_all(FilamentAutomation) if not a.is_armed]
                self._start_filament_detection(not_armed)
            self._decide_all()
        elif isinstance(event, _WaitForTemperature):
            self._waiting_temperature.add(event.index_id)
            self._decide_temp_hum_controls(self._get_sensor_data(), None)
        elif isinstance(event, _StopTempHumControls):
            self._stop_temp_hum_controls()

    def _decide_gpio_input_levels(self) -> None:
        try:
            for rule in self._automations.get_all(RuleAutomation):
                # Get automation rule trigger and reaction
                trigger, reaction = rule.trigger, rule.reaction

                # Skip automation rules which don't react to gpio inputs
                if not isinstance(trigger, GpioInputTrigger) or not isinstance(reaction, OutputControlReaction):
                    continue

                # Get the trigger input id
                input_id = trigger.config.input

                # Get the input level
                try:
                    level = self._gpio_inputs.get(input_id).read_pin_level()
                except GpioInputError as error:
                    self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                    continue

                # React if the input level matches the trigger
                if trigger.matches_level(level):
                    self._control_output(reaction)
        except Exception:
            self._logger.exception("Error applying the levels of the GPIO inputs")

    def _decide_all(self) -> None:
        sensor_data = self._get_sensor_data()

        self._decide_temp_hum_controls(sensor_data, None)
        self._decide_pwm_linked_temperature(sensor_data, None)

        self._update_ui()

    def _decide_temp_hum_controls(self, sensor_data: list[dict], sensor_id: int | None) -> None:
        try:
            for rpi_output in self._settings.rpi_outputs:
                # Only the temperature and humidity controls
                if rpi_output["output_type"] != "temp_hum_control":
                    continue

                # Get output id
                index_id = to_int(rpi_output["index_id"])

                # Get the output parsed settings
                try:
                    control = self._outputs.get(index_id, TempHumControlOutput)
                except OutputError:
                    # If the settings are invalid, we can only skip this output.
                    # There is no risk, as with invalid settings it can't be on in the first place.
                    continue

                # If we received a temperature event, check if it is from the sensor linked to this output
                if sensor_id is not None and control.config.linked_temp_sensor != sensor_id:
                    continue

                # Get linked sensor data
                linked_sensor_data = self._get_linked_sensor_data(sensor_data, control.config.linked_temp_sensor)
                temperature = None if linked_sensor_data is None else linked_sensor_data["temperature"]
                humidity = None if linked_sensor_data is None else linked_sensor_data["humidity"]

                # Forward the sensor data to the temperature and humidity control
                previous_status = control.status
                try:
                    status = control.regulate(temperature, humidity)
                except Exception:
                    self._logger.exception("Error reading or writing output %s", index_id)
                    continue

                # If the control status has remained unchanged, we are done
                if status is previous_status:
                    continue

                # Update UI
                self._update_ui()

            # Resume the print paused by ENC W1 once every control it waits for is at its target
            self._decide_waiting_print()
        except Exception:
            self._logger.exception("Error handling temperature/humidity control")

    def _decide_waiting_print(self) -> None:
        # Avoid resuming prints if they were not paused to wait for temperatures
        if not self._waiting_temperature:
            return

        for index_id in list(self._waiting_temperature):
            # Get the temperature/humidity control we are waiting for
            try:
                control = self._outputs.get(index_id, TempHumControlOutput)
            except OutputError:
                self._waiting_temperature.discard(index_id)
                continue

            # Check if the temperature/humidity control has not reached the temperature yet
            if control.status is not TempHumControlStatus.IDLE:
                return

        # Resume the print
        if self._printer.is_paused():
            self._waiting_temperature.clear()
            self._printer.resume_print()

    def _decide_temperature_rules(self, sensor_data: list[dict], sensor_id: int) -> None:
        for rule in self._automations.get_all(RuleAutomation):
            # Get the automation trigger
            trigger = rule.trigger

            # Skip if the trigger is not a temperature one or if it is not linked to the sensor id received
            if not isinstance(trigger, TemperatureTrigger) or trigger.config.linked_temp_sensor != sensor_id:
                continue

            # Get linked sensor data
            linked_data = self._get_linked_sensor_data(sensor_data, trigger.config.linked_temp_sensor)
            temperature = None if linked_data is None else linked_data["temperature"]

            # React if the automation trigger matches the temperature
            if trigger.matches_temperature(temperature):
                self._react_to_temperature(rule, trigger.config.alarm_set_temp)

    def _react_to_temperature(self, rule: RuleAutomation, threshold: float) -> None:
        reaction = rule.reaction
        cause = f"enclosure temperature exceed {threshold:g}"
        try:
            if isinstance(reaction, OutputControlReaction):
                if self._control_output(reaction):
                    self._notifications.send(NotificationType.TEMPERATURE_ACTION, f"Temperature action: {cause}")
            elif isinstance(reaction, RunActionReaction):
                action = self._run_action(reaction.config.action)
                if isinstance(action, GcodeAction):
                    self._notifications.send(NotificationType.TEMPERATURE_ACTION, f"Temperature action: {cause}")
                elif isinstance(action, PrinterAction):
                    self._notifications.send(
                        NotificationType.PRINTER_ACTION,
                        f"Printer action: {action.config.printer_action.value} caused by {cause}",
                    )
            elif isinstance(reaction, StopTempHumControlReaction):
                self._stop_temp_hum_controls()
                self._notifications.send(
                    NotificationType.PRINTER_ACTION,
                    f"Printer action: stop_temp_hum_control caused by {cause}",
                )
        except Exception:
            self._logger.exception("Error handling an automation on the temperature above %s", threshold)

    def _decide_pwm_linked_temperature(self, sensor_data: list[dict], sensor_id: int | None) -> None:
        # The curve drives the PWM only while a print job is on, paused included
        if not self._print_job_running:
            return

        try:
            for automation in self._automations.get_all(PwmTemperatureLinkedAutomation):
                # If we received a temperature event, check if it is from the sensor linked to this automation
                if sensor_id is not None and automation.config.linked_temp_sensor != sensor_id:
                    continue

                # Get the automation output
                output_id = automation.config.output

                # Get linked sensor data
                linked_data = self._get_linked_sensor_data(sensor_data, automation.config.linked_temp_sensor)
                temperature = None if linked_data is None else linked_data["temperature"]

                # Calculate the new duty cycle
                calculated_duty = automation.get_duty_cycle(temperature)

                # Write the new duty cycle to the output
                self._write_pwm(output_id, calculated_duty)
        except Exception:
            self._logger.exception("Error handling temperature linked PWM outputs")

    def _reset_pwm_linked_temperature(self) -> None:
        automations = self._automations.get_all(PwmTemperatureLinkedAutomation)
        for output_id in dict.fromkeys(automation.config.output for automation in automations):
            try:
                default_duty_cycle = self._outputs.get(output_id, PwmOutput).config.default_duty_cycle
            except OutputError as error:
                self._logger.debug("Can't reset the duty cycle of output %s: %s", output_id, error)
            else:
                self._write_pwm(output_id, default_duty_cycle)

    def _decide_gpio_input_edge(self, input_id: int, level: int) -> None:
        input_label = next(
            (
                rpi_input["label"]
                for rpi_input in self._settings.rpi_inputs
                if to_int(rpi_input["index_id"]) == input_id
            ),
            "",
        )
        for automation in self._automations.get_triggered_by_gpio_input(input_id, level):
            if isinstance(automation, RuleAutomation):
                self._react_to_gpio_edge(automation, input_id, input_label)
            elif isinstance(automation, FilamentAutomation):
                self._detect_filament_end(automation, input_id, input_label)

    def _react_to_gpio_edge(self, rule: RuleAutomation, input_id: int, input_label: str) -> None:
        reaction = rule.reaction
        try:
            if isinstance(reaction, OutputControlReaction):
                config = reaction.config
                if self._control_output(reaction):
                    self._notifications.send(
                        NotificationType.GPIO_ACTION,
                        f"GPIO control action caused by input {input_label}. "
                        f"Setting GPIO{config.controlled_io} to: {config.controlled_io_set_state.value}",
                    )
            elif isinstance(reaction, RunActionReaction):
                action = self._run_action(reaction.config.action)
                if isinstance(action, GcodeAction):
                    self._notifications.send(
                        NotificationType.GPIO_ACTION,
                        f"GPIO control action caused by input {input_label}. Sending GCODE command",
                    )
                elif isinstance(action, PrinterAction):
                    self._notifications.send(
                        NotificationType.PRINTER_ACTION,
                        f"Printer action: {action.config.printer_action.value} caused by input: {input_label}",
                    )
            elif isinstance(reaction, StopTempHumControlReaction):
                self._stop_temp_hum_controls()
                self._notifications.send(
                    NotificationType.PRINTER_ACTION,
                    f"Printer action: stop_temp_hum_control caused by input: {input_label}",
                )
        except Exception:
            self._logger.exception("Error handling an automation of input %s", input_id)

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

    def _decide_print_job_event(self, event: str) -> None:
        if event == Events.PRINT_STARTED:
            self._print_job_running = True
            self._start_filament_detection(self._automations.get_all(FilamentAutomation))
        elif event == Events.PRINT_RESUMED:
            self._waiting_temperature.clear()
            self._start_filament_detection(self._automations.get_all(FilamentAutomation))
        elif event == Events.PRINT_PAUSED:
            self._decide_waiting_print()
        elif event in (Events.PRINT_DONE, Events.PRINT_CANCELLED, Events.PRINT_FAILED):
            self._print_job_running = False
            self._waiting_temperature.clear()
            for automation in self._automations.get_all(FilamentAutomation):
                automation.disarm()
            self._reset_pwm_linked_temperature()

    def _start_filament_detection(self, automations: Iterable[FilamentAutomation]) -> None:
        try:
            for automation in automations:
                automation.disarm()

                input_id = automation.trigger.config.input

                try:
                    level = self._gpio_inputs.get(input_id).read_pin_level()
                except GpioInputError as error:
                    self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                    continue

                if automation.is_filament_missing(level):
                    self._printer.pause_print()
                    self._logger.info("Started printing with no filament.")
                else:
                    automation.arm()
        except Exception:
            self._logger.exception("Error starting filament detection")

    def _stop_temp_hum_controls(self) -> None:
        for rpi_output in self._settings.rpi_outputs:
            if rpi_output["auto_shutdown"] and rpi_output["output_type"] == "temp_hum_control":
                index_id = to_int(rpi_output["index_id"])
                try:
                    self._outputs.get(index_id, TempHumControlOutput).set_target(0.0)
                except OutputError as error:
                    self._logger.debug("Can't set the target of output %s: %s", index_id, error)
        self._decide_temp_hum_controls(self._get_sensor_data(), None)

    def _turn_off_all_outputs(self) -> None:
        for output in self._outputs.get_all(Output):
            try:
                output.turn_off()
            except OutputError as error:
                self._logger.debug("Can't turn off an output: %s", error)
            except Exception:
                self._logger.exception("Error turning off an output")

    def _control_output(self, reaction: OutputControlReaction) -> bool:
        config = reaction.config
        try:
            self._outputs.get(config.controlled_io, RegularOutput)
        except OutputError:
            return False
        self._switch_output(config.controlled_io, config.controlled_io_set_state)
        return True

    def _run_action(self, index_id: int) -> Action | None:
        try:
            action = self._actions.get(index_id, Action)
            action.run()
        except ActionError as error:
            self._logger.debug("Can't run action %s: %s", index_id, error)
            return None
        return action

    def _get_linked_sensor_data(self, sensor_data: list[dict], linked_id: int) -> dict | None:
        return next((data for data in sensor_data if data["index_id"] == linked_id), None)
