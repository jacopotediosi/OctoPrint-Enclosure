from __future__ import annotations

import logging
from dataclasses import fields
from typing import TYPE_CHECKING

from octoprint_enclosure.automations import OutputSetState
from octoprint_enclosure.outputs import Output, OutputError, ThermostatOutput

if TYPE_CHECKING:
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

    def control(
        self,
        index_id: int,
        state: OutputSetState,
        setpoint_config: OutputSetpointConfig,
        origin: str,
        *,
        log_level: int = logging.INFO,
    ) -> bool:
        """Turn an output on or off, or toggle it.

        Args:
            index_id (int): The id of the output.
            state (OutputSetState): What to do with the output.
            setpoint_config (OutputSetpointConfig): The setpoint the output is turned on to.
            origin (str): Who asks for it, e.g. "automation 40".
            log_level (int): The level at which the change of the output is logged.

        Returns:
            bool: Whether the output has been successfully controlled: False if it is not set up.

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
                self._thermostat_decision.set_target(index_id, None, origin, log_level=log_level)
            else:
                self._thermostat_decision.set_target(index_id, setpoint_values["target"], origin, log_level=log_level)
        elif state is OutputSetState.ON:
            setpoint = setpoint_class(**setpoint_values)
            self._output_executor.turn_on(index_id, setpoint, origin=origin, log_level=log_level)
        elif state is OutputSetState.OFF:
            self._output_executor.turn_off(index_id, origin=origin, log_level=log_level)
        else:
            setpoint = setpoint_class(**setpoint_values)
            self._output_executor.toggle(index_id, setpoint, origin=origin, log_level=log_level)

        return True
