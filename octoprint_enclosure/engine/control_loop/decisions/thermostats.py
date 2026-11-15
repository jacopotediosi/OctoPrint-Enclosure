from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint.events import Events
from typing_extensions import override

from octoprint_enclosure.automations import OctoprintEvent, ReadingEvent
from octoprint_enclosure.outputs import ThermostatStatus

from .base import Decision

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.automations import AutomationEvent, ConditionsState
    from octoprint_enclosure.engine.control_loop.thermostats import Thermostats
    from octoprint_enclosure.engine.output_executor import OutputExecutor
    from octoprint_enclosure.inputs import Reading, SensorPoller


class ThermostatDecision(Decision):
    """The decision regarding the thermostats.

    Each thermostat decides, from the readings of its sensor, whether its device has to be on. A print paused by
    ENC W1 waits here until the thermostats it asked for reach their target.
    """

    _sensor_poller: SensorPoller
    _output_executor: OutputExecutor
    _printer: PrinterInterface
    _thermostats: Thermostats
    _logger: logging.Logger

    _awaited_thermostat_ids: set[int]
    """The ids of the thermostats a paused print waits for, until they reach their target."""

    def __init__(
        self,
        sensor_poller: SensorPoller,
        output_executor: OutputExecutor,
        printer: PrinterInterface,
        thermostats: Thermostats,
        logger: logging.Logger,
    ) -> None:
        """Set up the decision regarding the thermostats.

        Args:
            sensor_poller (SensorPoller): The poller of the temperature sensors.
            output_executor (OutputExecutor): The executor of the commands to the outputs.
            printer (PrinterInterface): The OctoPrint printer interface.
            thermostats (Thermostats): The thermostats.
            logger (logging.Logger): The logger to write to.

        """
        self._sensor_poller = sensor_poller
        self._output_executor = output_executor
        self._printer = printer
        self._thermostats = thermostats
        self._logger = logger

        self._awaited_thermostat_ids = set()

    def set_target(self, index_id: int, target: float | None) -> None:
        """Set the target of a thermostat, and decide again whether its device has to be on.

        Args:
            index_id (int): The id of the output of the thermostat.
            target (float | None): The target temperature or humidity, or None to turn the thermostat off.

        """
        thermostat = self._thermostats.get(index_id)
        if thermostat is None:
            self._logger.debug("Can't set the target of output %s: it isn't a thermostat", index_id)
            return

        thermostat.set_target(target)
        self.regulate()

    def wait_for_target(self, index_id: int) -> None:
        """Make the paused print wait until a thermostat reaches its target.

        Args:
            index_id (int): The id of the output of the thermostat.

        """
        self._awaited_thermostat_ids.add(index_id)
        self.regulate()

    def regulate(self) -> None:
        """Decide again, from the last readings, whether the device of each thermostat has to be on."""
        self._regulate(self._sensor_poller.get_readings(), None)

    @override
    def decide(self, readings: Mapping[int, Reading], conditions_state: ConditionsState) -> None:
        """Decide whether the device of each thermostat has to be on, and switch it."""
        self._regulate(readings, None)

    @override
    def react(self, event: AutomationEvent, conditions_state: ConditionsState) -> None:
        """React to an automation event, e.g. decide the thermostats linked to a sensor that has a new reading."""
        if isinstance(event, ReadingEvent):
            self._regulate({event.index_id: event.reading}, event.index_id)
        elif isinstance(event, OctoprintEvent):
            if event.name == Events.PRINT_PAUSED:
                self._resume_print_if_targets_reached()
            elif event.name in (
                Events.PRINT_RESUMED,
                Events.PRINT_DONE,
                Events.PRINT_CANCELLED,
                Events.PRINT_FAILED,
            ):
                self._awaited_thermostat_ids.clear()

    def _regulate(self, readings: Mapping[int, Reading], sensor_id: int | None) -> None:
        for index_id, thermostat in self._thermostats.get_all().items():
            # Skip the thermostats that are not linked to the sensor with the new reading
            if sensor_id is not None and thermostat.config.linked_temp_sensor != sensor_id:
                continue

            # Get the reading of the linked sensor
            linked_reading = readings.get(thermostat.config.linked_temp_sensor)
            temperature = None if linked_reading is None else linked_reading.temperature
            humidity = None if linked_reading is None else linked_reading.humidity

            # Turn a heater off above its maximum temperature
            if thermostat.is_above_max_temp(temperature):
                self._logger.warning("Thermostat %s reached its maximum temperature: turning it off", index_id)
                thermostat.turn_off()

            # Decide whether the device has to be on, and switch it
            should_be_on = thermostat.decide(temperature, humidity)
            self._output_executor.switch_thermostat(index_id, on=should_be_on)

        # Resume the print paused by ENC W1 once every thermostat it waits for is at its target
        self._resume_print_if_targets_reached()

    def _resume_print_if_targets_reached(self) -> None:
        # Avoid resuming prints if there are no awaited thermostats (e.g., the user manually paused it)
        if not self._awaited_thermostat_ids:
            return

        # Stop waiting for the thermostats that don't exist anymore
        thermostats = self._thermostats.get_all()
        self._awaited_thermostat_ids.intersection_update(thermostats)

        # Don't resume if there are awaited thermostats that haven't reached their target yet
        if any(thermostats[index_id].status is not ThermostatStatus.IDLE for index_id in self._awaited_thermostat_ids):
            return

        # Resume the print
        if self._printer.is_paused():
            self._awaited_thermostat_ids.clear()
            self._printer.resume_print()
