from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING

from octoprint_enclosure.automations import OutputSetState
from octoprint_enclosure.outputs import Output, OutputError, ThermostatOutput

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.engine.control_loop.thermostats import Thermostats
    from octoprint_enclosure.engine.output_executor import OutputExecutor
    from octoprint_enclosure.outputs import Outputs, OutputSetpointConfig

    from .thermostats import ThermostatDecision


class OutputControl:
    """Turns the outputs on and off for the automations, each with the setpoint of its type."""

    _outputs: Outputs
    _output_executor: OutputExecutor
    _thermostats: Thermostats
    _thermostat_decision: ThermostatDecision
    _logger: logging.Logger

    def __init__(
        self,
        outputs: Outputs,
        output_executor: OutputExecutor,
        thermostats: Thermostats,
        thermostat_decision: ThermostatDecision,
        logger: logging.Logger,
    ) -> None:
        """Set up the control of the outputs.

        Args:
            outputs (Outputs): The outputs.
            output_executor (OutputExecutor): The executor of the commands to the outputs.
            thermostats (Thermostats): The thermostats.
            thermostat_decision (ThermostatDecision): The decision regarding the thermostats.
            logger (logging.Logger): The logger to write to.

        """
        self._outputs = outputs
        self._output_executor = output_executor
        self._thermostats = thermostats
        self._thermostat_decision = thermostat_decision
        self._logger = logger

    def control(self, index_id: int, state: OutputSetState, setpoint_config: OutputSetpointConfig) -> bool:
        """Turn an output on or off, or toggle it.

        Args:
            index_id (int): The id of the output.
            state (OutputSetState): What to do with the output.
            setpoint_config (OutputSetpointConfig): The setpoint the output is turned on to.

        Returns:
            bool: Whether the output has been successfully controlled: False if it is not set up, or if the setpoint to
                turn a thermostat on is not set.

        """
        try:
            output = self._outputs.get(index_id, Output)
        except OutputError:
            return False

        setpoint_class = output.setpoint_class
        setpoint_values = {field.name: getattr(setpoint_config, field.name) for field in fields(setpoint_class)}

        if isinstance(output, ThermostatOutput):
            thermostat = self._thermostats.get(index_id)
            if thermostat is None:
                return False

            if state is OutputSetState.OFF or (state is OutputSetState.TOGGLE and thermostat.is_on()):
                thermostat.turn_off()
            elif None in setpoint_values.values():
                self._logger.debug("Can't turn on output %s: its setpoint is not set", index_id)
                return False
            else:
                thermostat.turn_on(setpoint_class(**setpoint_values))

            self._thermostat_decision.regulate()
        elif state is OutputSetState.ON:
            self._output_executor.turn_on(index_id, setpoint_class(**setpoint_values))
        elif state is OutputSetState.OFF:
            self._output_executor.turn_off(index_id)
        else:
            self._output_executor.toggle(index_id, setpoint_class(**setpoint_values))

        return True
