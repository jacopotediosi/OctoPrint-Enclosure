from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint.events import Events

from .actions import ActionError, GcodeAction, GcodeConfig, PrinterAction
from .automations import (
    FilamentAutomation,
    GpioInputTrigger,
    OutputControlReaction,
    PwmTemperatureLinkedAutomation,
    RuleAutomation,
    RunActionReaction,
    StopThermostatsReaction,
    TemperatureTrigger,
)
from .inputs import GpioInputError
from .notifications import NotificationType
from .outputs import (
    OutputError,
    PwmOutput,
    RegularOutput,
    Thermostat,
    ThermostatOutput,
    ThermostatStatus,
)
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
    from .output_executor import OutputExecutor
    from .outputs import Outputs

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
class _ThermostatTargetChanged(_Event):
    """The target of a thermostat changed."""

    index_id: int
    """The id of the thermostat."""

    target: float
    """The new target temperature or humidity, or 0 if the thermostat turned off."""


@dataclass(frozen=True)
class _WaitForTemperature(_Event):
    """A print waits for a thermostat to reach its target."""

    index_id: int
    """The id of the thermostat."""


@dataclass(frozen=True)
class _StopThermostats(_Event):
    """The thermostats with Auto Shutdown on turn off."""


@dataclass(frozen=True)
class _UpdateUiTargets(_Event):
    """The UI asks for the targets of the thermostats."""


class ControlLoop:
    """Takes the decisions of the plugin on a thread of its own: what the outputs do, and when the automations act.

    This is the only place that decides whether an output is on or off, and the automations can also act on the
    printer. Every decision runs on this one thread, one at a time and always in the same order, so when several
    automations want the same output, who wins never depends on timing.
    """

    _gpio_inputs: GpioInputs
    _outputs: Outputs
    _actions: Actions
    _automations: Automations
    _output_executor: OutputExecutor
    _notifications: Notifications
    _printer: PrinterInterface
    _frontend: Frontend
    _settings: Settings
    _logger: logging.Logger

    _get_sensor_data: Callable[[], list[dict]]
    """The function giving the last reading of each sensor."""

    _thermostats: dict[int, Thermostat]
    """The thermostats, by the id of their output."""

    _print_job_running: bool
    """Whether a print job is running."""

    _waiting_temperature: set[int]
    """The ids of the thermostats a paused print waits for, until they reach their target."""

    _queue: queue.Queue[_Event]
    """The events to handle, in order."""

    _thread: threading.Thread

    def __init__(
        self,
        gpio_inputs: GpioInputs,
        outputs: Outputs,
        actions: Actions,
        automations: Automations,
        output_executor: OutputExecutor,
        notifications: Notifications,
        printer: PrinterInterface,
        frontend: Frontend,
        settings: Settings,
        logger: logging.Logger,
        *,
        get_sensor_data: Callable[[], list[dict]],
    ) -> None:
        """Set up the loop, with its thread ready to start.

        Args:
            gpio_inputs (GpioInputs): The GPIO inputs.
            outputs (Outputs): The outputs.
            actions (Actions): The actions.
            automations (Automations): The automations.
            output_executor (OutputExecutor): The executor of the commands to the outputs.
            notifications (Notifications): The notifications.
            printer (PrinterInterface): The OctoPrint printer interface.
            frontend (Frontend): The frontend handler.
            settings (Settings): The plugin settings.
            logger (logging.Logger): The logger to write to.
            get_sensor_data (Callable[[], list[dict]]): The function giving the last reading of each sensor, as a list
                of dicts with the keys index_id, temperature, humidity and airquality.

        """
        self._gpio_inputs = gpio_inputs
        self._outputs = outputs
        self._actions = actions
        self._automations = automations
        self._output_executor = output_executor
        self._notifications = notifications
        self._printer = printer
        self._frontend = frontend
        self._settings = settings
        self._logger = logger.getChild("ControlLoop")

        self._get_sensor_data = get_sensor_data

        self._thermostats = {}
        self._print_job_running = False
        self._waiting_temperature = set()
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="EnclosureControlLoop", daemon=True)

    def start(self) -> None:
        """Start taking decisions, on the Control Loop thread."""
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

    def set_thermostat_target(self, index_id: int, target: float) -> None:
        """Set the target of a thermostat, and take the decisions regarding it.

        Args:
            index_id (int): The id of the thermostat.
            target (float): The target temperature or humidity, or 0 to turn the thermostat off.

        """
        self._put(_ThermostatTargetChanged(index_id, target))

    def get_thermostat_targets(self) -> dict[int, float]:
        """Get the targets of the thermostats.

        Returns:
            dict[int, float]: The target temperature or humidity of each thermostat, 0 if it is off, by the id of
                its output.

        """
        return {index_id: thermostat.target for index_id, thermostat in self._thermostats.items()}

    def wait_for_temperature(self, index_id: int) -> None:
        """Resume the paused print once a thermostat reaches its target.

        Args:
            index_id (int): The id of the thermostat the print waits for.

        """
        self._put(_WaitForTemperature(index_id))

    def stop_thermostats(self) -> None:
        """Turn off the thermostats with Auto Shutdown on."""
        self._put(_StopThermostats())

    def update_ui_targets(self) -> None:
        """Update the targets of the thermostats in the UI."""
        self._put(_UpdateUiTargets())

    def _put(self, event: _Event) -> None:
        self._queue.put(event)

    def _run(self) -> None:
        try:
            self._start_deciding()
        except Exception:
            self._logger.exception("Error starting to decide")

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
        if isinstance(event, _Stop):
            self._output_executor.turn_off_all_outputs(wait=True)
        elif isinstance(event, _Tick):
            self._decide_all()
        elif isinstance(event, _NewReading):
            sensor_data = self._get_sensor_data()
            self._decide_thermostats(sensor_data, event.index_id)
            self._decide_temperature_rules(sensor_data, event.index_id)
            self._decide_pwm_linked_temperature(sensor_data, event.index_id)
        elif isinstance(event, _GpioInputEdge):
            self._decide_gpio_input_edge(event.input_id, event.level)
        elif isinstance(event, _PrintJobEvent):
            self._decide_print_job_event(event.event)
        elif isinstance(event, _SettingsLoaded):
            self._load_thermostats()
            self._frontend.update_targets(self.get_thermostat_targets())

            # While printing every filament automation has to watch: start the ones that don't yet
            if self._printer.is_printing():
                not_armed = [a for a in self._automations.get_all(FilamentAutomation) if not a.is_armed]
                self._start_filament_detection(not_armed)

            self._decide_all()
        elif isinstance(event, _ThermostatTargetChanged):
            thermostat = self._thermostats.get(event.index_id)
            if thermostat is None:
                self._logger.debug("Can't set the target of output %s: it isn't a thermostat", event.index_id)
            else:
                thermostat.set_target(event.target)
                self._frontend.update_targets(self.get_thermostat_targets())
                self._decide_thermostats(self._get_sensor_data(), None)
        elif isinstance(event, _WaitForTemperature):
            self._waiting_temperature.add(event.index_id)
            self._decide_thermostats(self._get_sensor_data(), None)
        elif isinstance(event, _StopThermostats):
            self._stop_thermostats()
        elif isinstance(event, _UpdateUiTargets):
            self._frontend.update_targets(self.get_thermostat_targets())

    def _start_deciding(self) -> None:
        self._load_thermostats()
        self._print_job_running = bool(self._printer.is_printing() or self._printer.is_paused())
        self._decide_gpio_input_levels()

    def _load_thermostats(self) -> None:
        thermostats: dict[int, Thermostat] = {}

        for rpi_output in self._settings.rpi_outputs:
            # Only the thermostats
            if rpi_output["output_type"] != "temp_hum_control":
                continue

            # Get the output
            index_id = to_int(rpi_output["index_id"])
            try:
                output = self._outputs.get(index_id, ThermostatOutput)
            except OutputError:
                # If the settings are invalid, we can only skip this thermostat.
                # There is no risk, as with invalid settings it can't be on in the first place.
                continue

            # Keep the thermostat of an output the settings didn't change, with its target
            thermostat = self._thermostats.get(index_id)
            if thermostat is None or thermostat.config is not output.config:
                thermostat = Thermostat(output.config)
            thermostats[index_id] = thermostat

        self._thermostats = thermostats

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

        self._decide_thermostats(sensor_data, None)
        self._decide_pwm_linked_temperature(sensor_data, None)

    def _decide_thermostats(self, sensor_data: list[dict], sensor_id: int | None) -> None:
        try:
            for index_id, thermostat in self._thermostats.items():
                # If we received a temperature event, check if it is from the sensor linked to this thermostat
                if sensor_id is not None and thermostat.config.linked_temp_sensor != sensor_id:
                    continue

                # Get linked sensor data
                linked_sensor_data = self._get_linked_sensor_data(sensor_data, thermostat.config.linked_temp_sensor)
                temperature = None if linked_sensor_data is None else linked_sensor_data["temperature"]
                humidity = None if linked_sensor_data is None else linked_sensor_data["humidity"]

                # Turn a heater off above its maximum temperature
                if thermostat.is_above_max_temp(temperature):
                    self._logger.warning("Thermostat %s reached its maximum temperature: turning it off", index_id)
                    thermostat.set_target(0.0)
                    self._frontend.update_targets(self.get_thermostat_targets())

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
                try:
                    action = self._actions.run(reaction.config.action)
                except ActionError as error:
                    self._logger.debug("Can't run action %s: %s", reaction.config.action, error)
                    return
                if isinstance(action, GcodeAction):
                    self._notifications.send(NotificationType.TEMPERATURE_ACTION, f"Temperature action: {cause}")
                elif isinstance(action, PrinterAction):
                    self._notifications.send(
                        NotificationType.PRINTER_ACTION,
                        f"Printer action: {action.config.printer_action.value} caused by {cause}",
                    )
            elif isinstance(reaction, StopThermostatsReaction):
                self._stop_thermostats()
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
                self._output_executor.write_pwm(output_id, calculated_duty)
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
                self._output_executor.write_pwm(output_id, default_duty_cycle)

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
                try:
                    action = self._actions.run(reaction.config.action)
                except ActionError as error:
                    self._logger.debug("Can't run action %s: %s", reaction.config.action, error)
                    return
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
            elif isinstance(reaction, StopThermostatsReaction):
                self._stop_thermostats()
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

    def _stop_thermostats(self) -> None:
        for rpi_output in self._settings.rpi_outputs:
            if rpi_output["auto_shutdown"] and rpi_output["output_type"] == "temp_hum_control":
                thermostat = self._thermostats.get(to_int(rpi_output["index_id"]))
                if thermostat is not None:
                    thermostat.set_target(0.0)
        self._frontend.update_targets(self.get_thermostat_targets())
        self._decide_thermostats(self._get_sensor_data(), None)

    def _control_output(self, reaction: OutputControlReaction) -> bool:
        config = reaction.config
        try:
            self._outputs.get(config.controlled_io, RegularOutput)
        except OutputError:
            return False
        self._output_executor.switch_output(config.controlled_io, config.controlled_io_set_state)
        return True

    def _get_linked_sensor_data(self, sensor_data: list[dict], linked_id: int) -> dict | None:
        return next((data for data in sensor_data if data["index_id"] == linked_id), None)
