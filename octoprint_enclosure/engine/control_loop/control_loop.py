from __future__ import annotations

import contextlib
import queue
import threading
import time
from typing import TYPE_CHECKING

from octoprint_enclosure.automations import GpioEdgeEvent, OctoprintEvent

from .decisions import Decisions
from .messages import (
    NewReading,
    SensorFailed,
    SetAutomationEnabled,
    SetThermostatTarget,
    SettingsLoaded,
    Started,
    Stop,
    Tick,
    UpdateUi,
    WaitForThermostatTarget,
)
from .thermostats import Thermostats

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping
    from typing import Any

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.actions import Actions
    from octoprint_enclosure.automations import AutomationEvent, Automations
    from octoprint_enclosure.engine.output_executor import OutputExecutor
    from octoprint_enclosure.engine.scheduler import Scheduler
    from octoprint_enclosure.frontend import Frontend
    from octoprint_enclosure.inputs import GpioInputs, SensorPoller, Sensors
    from octoprint_enclosure.integrations import Mqtt
    from octoprint_enclosure.notifications import Notifications
    from octoprint_enclosure.outputs import Outputs, Thermostat
    from octoprint_enclosure.settings import Settings

    from .messages import Message

TICK_INTERVAL_SECONDS = 10
"""The seconds between two ticks, at which the loop takes all the decisions again."""

WAIT_TIMEOUT_SECONDS = 5
"""The maximum seconds a caller waits for the loop to apply what it asked."""


class ControlLoop:
    """Takes the decisions of the plugin on its own thread, e.g. what the outputs do, and when the automations act."""

    _printer: PrinterInterface
    _logger: logging.Logger

    _queue: queue.Queue[Message | AutomationEvent]
    """The messages and the automation events to handle, in order."""

    _thermostats: Thermostats
    """The thermostats."""

    _decisions: Decisions
    """The decisions the thread takes for each message."""

    _thread: threading.Thread

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
        logger: logging.Logger,
    ) -> None:
        """Set up the loop, with its thread ready to start.

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
            logger (logging.Logger): The logger to write to.

        """
        self._printer = printer
        self._logger = logger.getChild("ControlLoop")

        self._queue = queue.Queue()
        self._thermostats = Thermostats(outputs, frontend)
        self._decisions = Decisions(
            sensors,
            gpio_inputs,
            sensor_poller,
            outputs,
            actions,
            automations,
            output_executor,
            scheduler,
            notifications,
            mqtt,
            printer,
            frontend,
            settings,
            self._thermostats,
            self._put,
            self._logger,
        )
        self._thread = threading.Thread(target=self._run, name="EnclosureControlLoop", daemon=True)

    def start(self) -> None:
        """Start taking decisions, on the Control Loop thread."""
        self._thread.start()

    def stop(self) -> None:
        """Stop taking decisions."""
        if self._thread.is_alive():
            self._put(Stop())
            self._thread.join()

    def evaluate_all(self) -> None:
        """Take all the decisions again now."""
        self._put(Tick())

    def evaluate_reading(self, sensor_id: int) -> None:
        """Take the decisions regarding a new sensor reading.

        Args:
            sensor_id (int): The id of the input of the sensor.

        """
        self._put(NewReading(sensor_id))

    def evaluate_sensor_failure(self, sensor_id: int) -> None:
        """Take the decisions regarding a sensor that stopped working.

        Args:
            sensor_id (int): The id of the input of the sensor.

        """
        self._put(SensorFailed(sensor_id))

    def evaluate_gpio_input_edge(self, input_id: int, level: int) -> None:
        """Take the decisions regarding an edge on a GPIO input.

        Args:
            input_id (int): The id of the input.
            level (int): The level of the input after the edge, 1 if high or 0 if low.

        """
        self._put(GpioEdgeEvent(input_id, level))

    def evaluate_octoprint_event(self, event_name: str, payload: Mapping[str, Any] | None) -> None:
        """Take the decisions regarding an event of OctoPrint.

        Args:
            event_name (str): The name of the event, as OctoPrint names it.
            payload (Mapping[str, Any] | None): The data OctoPrint sends with the event, or None if it sends none.

        """
        self._put(OctoprintEvent(event_name, payload))

    def evaluate_new_settings(self) -> None:
        """Take the decisions again after new settings were loaded."""
        self._put(SettingsLoaded())

    def set_thermostat_target(self, index_id: int, target: float | None, *, wait: bool = False) -> None:
        """Set the target of a thermostat, and take the decisions regarding it.

        Args:
            index_id (int): The id of the thermostat.
            target (float | None): The target temperature or humidity, or None to turn the thermostat off.
            wait (bool): Whether to wait until the target is applied and the device of the thermostat is switched.

        """
        done = threading.Event() if wait else None
        self._put(SetThermostatTarget(index_id, target, done))
        if done is not None and not done.wait(WAIT_TIMEOUT_SECONDS):
            self._logger.warning("Target of thermostat %s not applied after %s s", index_id, WAIT_TIMEOUT_SECONDS)

    def get_thermostats(self) -> dict[int, Thermostat]:
        """Get the thermostats.

        Returns:
            dict[int, Thermostat]: The thermostats, by the id of their output.

        """
        return self._thermostats.get_all()

    def pause_print_until_thermostat_target(self, index_id: int) -> None:
        """Pause the print, if one is running, until a thermostat reaches its target.

        Args:
            index_id (int): The id of the thermostat the print has to wait for.

        """
        if not self._printer.is_printing():
            return

        self._printer.pause_print()
        self._put(WaitForThermostatTarget(index_id))

    def set_automation_enabled(self, index_id: int, *, enabled: bool, wait: bool = False) -> None:
        """Enable or disable an automation, and take the decisions again.

        Args:
            index_id (int): The id of the automation.
            enabled (bool): Whether to enable the automation, or to disable it.
            wait (bool): Whether to wait until the automation is enabled or disabled.

        """
        done = threading.Event() if wait else None
        self._put(SetAutomationEnabled(index_id, enabled, done))
        if done is not None and not done.wait(WAIT_TIMEOUT_SECONDS):
            self._logger.warning(
                "Automation %s not %s after %s s",
                index_id,
                "enabled" if enabled else "disabled",
                WAIT_TIMEOUT_SECONDS,
            )

    def update_ui(self) -> None:
        """Update the UI."""
        self._put(UpdateUi())

    def _put(self, message: Message | AutomationEvent) -> None:
        self._queue.put(message)

    def _run(self) -> None:
        next_tick = time.monotonic() + TICK_INTERVAL_SECONDS
        message: Message | AutomationEvent | None = Started()

        while not isinstance(message, Stop):
            # Handle the message
            try:
                self._decisions.handle(message)
            except Exception:
                self._logger.exception("Error handling %s", message)

            # Wait for the next message, until the next tick
            message = None
            timeout = next_tick - time.monotonic()
            if timeout > 0:
                with contextlib.suppress(queue.Empty):
                    message = self._queue.get(timeout=timeout)

            # No message came before the tick
            if message is None:
                message = Tick()
                next_tick = time.monotonic() + TICK_INTERVAL_SECONDS
