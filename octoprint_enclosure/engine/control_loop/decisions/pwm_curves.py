from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.automations import PwmTemperatureLinkedAutomation, ReadingEvent
from octoprint_enclosure.outputs import PwmSetpoint

from .base import Decision

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping

    from octoprint_enclosure.automations import AutomationEvent, Automations, ConditionsState
    from octoprint_enclosure.engine.output_executor import OutputExecutor
    from octoprint_enclosure.inputs import Reading


class PwmCurveDecision(Decision):
    """The decision regarding the PWM curves.

    Each curve sets the duty cycle of a PWM output based on a temperature read by a sensor.
    """

    _automations: Automations
    _output_executor: OutputExecutor
    _logger: logging.Logger

    def __init__(self, automations: Automations, output_executor: OutputExecutor, logger: logging.Logger) -> None:
        """Set up the decision regarding the PWM curves automations.

        Args:
            automations (Automations): The automations.
            output_executor (OutputExecutor): The executor of the commands to the outputs.
            logger (logging.Logger): The logger to write to.

        """
        self._automations = automations
        self._output_executor = output_executor
        self._logger = logger

    @override
    def decide(self, readings: Mapping[int, Reading], conditions_state: ConditionsState) -> None:
        self._set_duty_cycles(readings, None, conditions_state)

    @override
    def react(self, event: AutomationEvent, conditions_state: ConditionsState) -> None:
        if isinstance(event, ReadingEvent):
            self._set_duty_cycles({event.index_id: event.reading}, event.index_id, conditions_state)

    def _set_duty_cycles(
        self,
        readings: Mapping[int, Reading],
        sensor_id: int | None,
        conditions_state: ConditionsState,
    ) -> None:
        for automation in self._automations.get_all(PwmTemperatureLinkedAutomation):
            # A curve drives the PWM only while its conditions are satisfied
            if not automation.conditions_satisfied(conditions_state):
                if automation.is_running:
                    self._stop_and_turn_off(automation)
                continue

            # Skip the curves that are not linked to the sensor with the new reading
            if sensor_id is not None and automation.config.linked_temp_sensor != sensor_id:
                continue

            # Get the automation output
            output_id = automation.config.output

            # Get the reading of the linked sensor
            linked_reading = readings.get(automation.config.linked_temp_sensor)
            temperature = None if linked_reading is None else linked_reading.temperature

            # Calculate the new duty cycle
            duty_cycle = automation.get_duty_cycle(temperature)

            # Write the new duty cycle to the output
            self._output_executor.turn_on(output_id, PwmSetpoint(duty_cycle))
            automation.start()

    def _stop_and_turn_off(self, automation: PwmTemperatureLinkedAutomation) -> None:
        self._output_executor.turn_off(automation.config.output)
        automation.stop()
