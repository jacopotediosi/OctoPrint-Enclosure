from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.outputs import Output, OutputError, ThermostatOutput
from octoprint_enclosure.utils import MeasurementType, get_gcode_param, parse_float

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from octoprint.util.comm import MachineCom

    from octoprint_enclosure.engine import OutputExecutor
    from octoprint_enclosure.outputs import Outputs
    from octoprint_enclosure.plugin_context import PluginContext
    from octoprint_enclosure.settings import Settings


class EncHandler:
    """Handles the ENC G-code commands."""

    _settings: Settings
    _outputs: Outputs
    _output_executor: OutputExecutor
    _logger: logging.Logger

    _set_temperature: Callable[[int, float | None, bool], None]
    """The function called to set the target of a thermostat, with the id of the output, the target (in Celsius for a
    temperature, or None to turn the thermostat off) and whether the print has to pause until the target is
    reached."""

    def __init__(
        self,
        plugin_context: PluginContext,
        set_temperature: Callable[[int, float | None, bool], None],
    ) -> None:
        """Set up the handler.

        Args:
            plugin_context (PluginContext): The plugin context.
            set_temperature (Callable[[int, float | None, bool], None]): The function called to set the target of a
                thermostat, with the id of the output, the target (in Celsius for a temperature, or None to turn the
                thermostat off) and whether the print has to pause until the target is reached.

        """
        self._settings = plugin_context.settings
        self._outputs = plugin_context.outputs
        self._output_executor = plugin_context.output_executor
        self._logger = plugin_context.logger.getChild("EncHandler")
        self._set_temperature = set_temperature

    def handle(self, comm_instance: MachineCom, cmd: str) -> None:
        """Run a G-code line, if it is an ENC command.

        Args:
            comm_instance (MachineCom): The connection to the printer, whose terminal the replies are written to.
            cmd (str): The G-code line.

        """
        if not self._settings.gcode_control or not cmd.strip().startswith("ENC"):
            return

        self._logger.debug("Received ENC command: %s", cmd)
        try:
            index_id = int(get_gcode_param(cmd, "O"))
        except ValueError as error:
            self._logger.warning("Can't run ENC command %s: %s", cmd, error)
            return

        try:
            output = self._outputs.get(index_id, Output)
        except OutputError as error:
            self._logger.debug("Can't run ENC command %s: %s", cmd, error)
            return

        if isinstance(output, ThermostatOutput):
            try:
                value = parse_float(get_gcode_param(cmd, "S"))
                wait = int(get_gcode_param(cmd, "W")) == 1
            except ValueError as error:
                self._logger.warning("Can't run ENC command %s: %s", cmd, error)
                return

            # S0 turns the thermostat off, in every unit
            target = None if value == 0 else value
            if target is not None and output.config.temp_ctr_type.measurement_type is MeasurementType.TEMPERATURE:
                target = self._settings.temperature_unit.to_celsius(target)

            self._set_temperature(index_id, target, wait)

            comm_instance._log(f"Setting thermostat output {index_id} to value {value}")
        else:
            reply = self._output_executor.run_enc_command(index_id, cmd, wait=True)

            if reply is not None:
                comm_instance._log(reply)
