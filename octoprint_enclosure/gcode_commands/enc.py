from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.outputs import Output, OutputError, ThermostatOutput
from octoprint_enclosure.utils import MeasurementType, get_gcode_param, parse_float

if TYPE_CHECKING:
    import logging

    from octoprint.printer import PrinterInterface

    from octoprint_enclosure.engine import ControlLoop, OutputExecutor
    from octoprint_enclosure.outputs import Outputs
    from octoprint_enclosure.plugin_context import PluginContext
    from octoprint_enclosure.settings import Settings


class EncHandler:
    """Handles the ENC G-code commands."""

    _settings: Settings
    _printer: PrinterInterface
    _outputs: Outputs
    _output_executor: OutputExecutor
    _control_loop: ControlLoop
    _logger: logging.Logger

    def __init__(self, plugin_context: PluginContext) -> None:
        """Set up the handler.

        Args:
            plugin_context (PluginContext): The plugin context.

        """
        self._settings = plugin_context.settings
        self._printer = plugin_context.printer
        self._outputs = plugin_context.outputs
        self._output_executor = plugin_context.output_executor
        self._control_loop = plugin_context.control_loop
        self._logger = plugin_context.logger.getChild("EncHandler")

    def handle(self, cmd: str) -> None:
        """Run a G-code line, if it is an ENC command.

        Args:
            cmd (str): The G-code line.

        """
        if not cmd.strip().startswith("ENC"):
            return

        if not self._settings.gcode_control:
            self._logger.warning("Can't run ENC command %s: ENC commands are not enabled", cmd)
            return

        self._logger.info("Received ENC command: %s", cmd)
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

            self._control_loop.set_thermostat_target(index_id, target, origin="ENC")
            if wait:
                self._control_loop.pause_print_until_thermostat_target(index_id)

            self._printer.log_lines(f"Setting thermostat output {index_id} to value {value}")
        else:
            reply = self._output_executor.run_enc_command(index_id, cmd, origin="ENC", wait=True)

            if reply is not None:
                self._printer.log_lines(reply)
