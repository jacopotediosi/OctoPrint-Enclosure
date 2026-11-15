from __future__ import annotations

import contextlib
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from octoprint.events import Events

from octoprint_enclosure.automations import (
    Automation,
    AutomationError,
    ConditionsState,
    GpioEdgeEvent,
    OctoprintEvent,
    ReadingEvent,
)
from octoprint_enclosure.engine.control_loop.messages import (
    NewReading,
    RunAutomationRuleReactions,
    SensorFailed,
    SetAutomationEnabled,
    SetThermostatTarget,
    SettingsLoaded,
    Started,
    SwitchToggleTimerOutput,
    Tick,
    UpdateUi,
    WaitForThermostatTarget,
)
from octoprint_enclosure.inputs import Reading

from .automation_rules import AutomationRuleDecision
from .filament_sensors import FilamentSensorDecision
from .output_control import OutputControl
from .pwm_curves import PwmCurveDecision
from .thermostats import ThermostatDecision
from .toggle_timers import ToggleTimerDecision

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.actions import Actions
    from octoprint_enclosure.automations import AutomationEvent, Automations
    from octoprint_enclosure.engine.control_loop.messages import Message
    from octoprint_enclosure.engine.control_loop.thermostats import Thermostats
    from octoprint_enclosure.engine.output_executor import OutputExecutor
    from octoprint_enclosure.engine.scheduler import Scheduler
    from octoprint_enclosure.frontend import Frontend
    from octoprint_enclosure.inputs import GpioInputs, SensorPoller, Sensors
    from octoprint_enclosure.integrations import Mqtt
    from octoprint_enclosure.notifications import Notifications
    from octoprint_enclosure.outputs import Outputs
    from octoprint_enclosure.settings import Settings

    from .base import Decision


class Decisions:
    """The decisions of the plugin.

    Each message of the Control Loop is handled here, on the Control Loop thread. This is the only place that says
    what is decided for each message, and in which order.
    """

    _sensors: Sensors
    _sensor_poller: SensorPoller
    _automations: Automations
    _output_executor: OutputExecutor
    _mqtt: Mqtt
    _printer: PrinterInterface
    _frontend: Frontend
    _settings: Settings
    _thermostats: Thermostats
    _logger: logging.Logger

    _conditions_state: ConditionsState
    """The current state of the things that the automation conditions check."""

    _thermostat_decision: ThermostatDecision
    _pwm_curve_decision: PwmCurveDecision
    _toggle_timer_decision: ToggleTimerDecision
    _filament_sensor_decision: FilamentSensorDecision
    _automation_rule_decision: AutomationRuleDecision
    _decisions: tuple[Decision, ...]
    """The decisions, in the order in which they are taken."""

    _handlers: dict[type, Callable[[Any], None]]
    """The methods that handle the control loop messages and the automation events, by their type."""

    def __init__(
        self,
        sensors: Sensors,
        gpio_inputs: GpioInputs,
        sensor_poller: SensorPoller,
        outputs: Outputs,
        actions: Actions,
        automations: Automations,
        output_executor: OutputExecutor,
        scheduler: Scheduler,
        notifications: Notifications,
        mqtt: Mqtt,
        printer: PrinterInterface,
        frontend: Frontend,
        settings: Settings,
        thermostats: Thermostats,
        put: Callable[[Message | AutomationEvent], object],
        logger: logging.Logger,
    ) -> None:
        """Set up the decisions.

        Args:
            sensors (Sensors): The temperature sensors.
            gpio_inputs (GpioInputs): The GPIO inputs.
            sensor_poller (SensorPoller): The poller of the temperature sensors.
            outputs (Outputs): The outputs.
            actions (Actions): The actions.
            automations (Automations): The automations.
            output_executor (OutputExecutor): The executor of the commands to the outputs.
            scheduler (Scheduler): The scheduler.
            notifications (Notifications): The notifications.
            mqtt (Mqtt): The MQTT broker.
            printer (PrinterInterface): The OctoPrint printer interface.
            frontend (Frontend): The frontend handler.
            settings (Settings): The plugin settings.
            thermostats (Thermostats): The thermostats.
            put (Callable[[Message | AutomationEvent], object]): The function that queues a message or an automation
                event for the Control Loop.
            logger (logging.Logger): The logger to write to.

        """
        self._sensors = sensors
        self._sensor_poller = sensor_poller
        self._automations = automations
        self._output_executor = output_executor
        self._mqtt = mqtt
        self._printer = printer
        self._frontend = frontend
        self._settings = settings
        self._thermostats = thermostats
        self._logger = logger

        self._conditions_state = ConditionsState()

        self._thermostat_decision = ThermostatDecision(sensor_poller, output_executor, printer, thermostats, logger)
        output_control = OutputControl(outputs, output_executor, thermostats, self._thermostat_decision, logger)
        self._pwm_curve_decision = PwmCurveDecision(automations, output_executor, logger)
        self._toggle_timer_decision = ToggleTimerDecision(automations, scheduler, output_control, put, logger)
        self._filament_sensor_decision = FilamentSensorDecision(
            gpio_inputs,
            actions,
            automations,
            notifications,
            printer,
            logger,
        )
        self._automation_rule_decision = AutomationRuleDecision(
            sensors,
            gpio_inputs,
            actions,
            automations,
            scheduler,
            notifications,
            settings,
            output_control,
            put,
            logger,
        )
        self._decisions = (
            self._thermostat_decision,
            self._pwm_curve_decision,
            self._toggle_timer_decision,
            self._filament_sensor_decision,
            self._automation_rule_decision,
        )

        self._handlers = {
            Started: self._handle_started,
            NewReading: self._handle_new_reading,
            SensorFailed: self._handle_sensor_failed,
            SettingsLoaded: self._handle_settings_loaded,
            GpioEdgeEvent: self._react,
            OctoprintEvent: self._handle_octoprint_event,
            Tick: self._handle_tick,
            SetThermostatTarget: self._handle_set_thermostat_target,
            WaitForThermostatTarget: self._handle_wait_for_thermostat_target,
            SetAutomationEnabled: self._handle_set_automation_enabled,
            RunAutomationRuleReactions: self._handle_run_automation_rule_reactions,
            SwitchToggleTimerOutput: self._handle_switch_toggle_timer_output,
            UpdateUi: self._handle_update_ui,
        }

    def handle(self, message: Message | AutomationEvent) -> None:
        """Take the decisions regarding a control loop message or an automation event.

        Args:
            message (Message | AutomationEvent): The message to the Control Loop thread, or the automation event,
                e.g. an edge on a GPIO input or an event of OctoPrint.

        """
        handler = self._handlers.get(type(message))
        if handler is None:
            self._logger.error("No handler for %s", message)
            return

        handler(message)

    def _handle_started(self, message: Started) -> None:
        self._thermostats.load()

        self._conditions_state.print_job_running = bool(self._printer.is_printing() or self._printer.is_paused())
        self._decide()

        self._automation_rule_decision.apply_gpio_input_levels(self._conditions_state)

    def _handle_new_reading(self, message: NewReading) -> None:
        # Get the reading of the sensor
        try:
            reading = self._sensor_poller.get_reading(message.sensor_id)
        except LookupError:
            reading = Reading()

        # React to the reading
        self._react(ReadingEvent(message.sensor_id, reading))

        # Update readings in the UI
        self._frontend.update_inputs()

        # Publish the reading on MQTT
        if reading.temperature is not None or reading.humidity is not None:
            with contextlib.suppress(LookupError):
                label = self._sensors.get(message.sensor_id).config.label
                temperature_unit = self._settings.temperature_unit
                temperature = (
                    None if reading.temperature is None else temperature_unit.from_celsius(reading.temperature)
                )
                self._mqtt.publish_sensor_reading(label, temperature, reading.humidity)

    def _handle_sensor_failed(self, message: SensorFailed) -> None:
        self._automation_rule_decision.notify_sensor_failure(message.sensor_id)

    def _handle_settings_loaded(self, message: SettingsLoaded) -> None:
        self._thermostats.load()
        self._decide()
        self._output_executor.update_ui_outputs()

    def _handle_octoprint_event(self, event: OctoprintEvent) -> None:
        # Update the conditions state
        previous_state = replace(self._conditions_state)
        if event.name == Events.PRINT_STARTED:
            self._conditions_state.print_job_running = True
        elif event.name in (Events.PRINT_DONE, Events.PRINT_CANCELLED, Events.PRINT_FAILED):
            self._conditions_state.print_job_running = False

        # Decide again if the state changed
        if self._conditions_state != previous_state:
            self._decide()

        # React to the event
        self._react(event)

    def _handle_tick(self, message: Tick) -> None:
        self._decide()

    def _handle_set_thermostat_target(self, message: SetThermostatTarget) -> None:
        try:
            self._thermostat_decision.set_target(message.index_id, message.target)
        finally:
            if message.done is not None:
                self._output_executor.run_after_commands(message.done.set)

    def _handle_wait_for_thermostat_target(self, message: WaitForThermostatTarget) -> None:
        self._thermostat_decision.wait_for_target(message.index_id)

    def _handle_set_automation_enabled(self, message: SetAutomationEnabled) -> None:
        try:
            automation = self._automations.get(message.index_id, Automation)
        except AutomationError as error:
            self._logger.debug("Can't enable or disable automation %s: %s", message.index_id, error)
        else:
            automation.enabled = message.enabled
            self._frontend.update_automations()
        finally:
            if message.done is not None:
                message.done.set()
        self._decide()

    def _handle_run_automation_rule_reactions(self, message: RunAutomationRuleReactions) -> None:
        self._automation_rule_decision.run_reactions(message, self._conditions_state)

    def _handle_switch_toggle_timer_output(self, message: SwitchToggleTimerOutput) -> None:
        self._toggle_timer_decision.switch_output(message, self._conditions_state)

    def _handle_update_ui(self, message: UpdateUi) -> None:
        self._frontend.update_inputs()
        self._frontend.update_automations()
        self._output_executor.update_ui_outputs()

    def _decide(self) -> None:
        readings = self._sensor_poller.get_readings()

        for decision in self._decisions:
            try:
                decision.decide(readings, self._conditions_state)
            except Exception:
                self._logger.exception("Error in %s while deciding", type(decision).__name__)

    def _react(self, event: AutomationEvent) -> None:
        for decision in self._decisions:
            try:
                decision.react(event, self._conditions_state)
            except Exception:
                self._logger.exception("Error in %s while reacting to %s", type(decision).__name__, event)
