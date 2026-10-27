from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import get_gcode_param, to_float, to_int

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from octoprint.util.comm import MachineCom

    from octoprint_enclosure.core import PluginContext, Settings
    from octoprint_enclosure.executor import Executor


class EncHandler:
    """Handles the ENC G-code commands."""

    _settings: Settings
    _executor: Executor
    _logger: logging.Logger

    _set_temperature: Callable[[int, float, bool], None]
    """The function called to set the target of a thermostat, with the id of the output,
    the target and whether the print has to pause until the target is reached."""

    _update_ui: Callable[[], None]
    """The function called to refresh the UI after an output changed."""

    def __init__(
        self,
        plugin_context: PluginContext,
        set_temperature: Callable[[int, float, bool], None],
        update_ui: Callable[[], None],
    ) -> None:
        """Set up the handler.

        Args:
            plugin_context (PluginContext): The plugin context.
            set_temperature (Callable[[int, float, bool], None]): The function called to set the target of a
                thermostat, with the id of the output, the target and whether the print has to pause
                until the target is reached.
            update_ui (Callable[[], None]): The function called to refresh the UI after an output changed.

        """
        self._settings = plugin_context.settings
        self._executor = plugin_context.executor
        self._logger = plugin_context.logger.getChild("EncHandler")
        self._set_temperature = set_temperature
        self._update_ui = update_ui

    def handle(self, comm_instance: MachineCom, cmd: str) -> None:
        """Run a G-code line, if it is an ENC command.

        Args:
            comm_instance (MachineCom): The connection to the printer, whose terminal the replies are written to.
            cmd (str): The G-code line.

        """
        if not self._settings.gcode_control or not cmd.strip().startswith("ENC"):
            return

        self._logger.debug("Received ENC command: %s", cmd)

        index_id = to_int(get_gcode_param(cmd, "O"))
        output = next((item for item in self._settings.rpi_outputs if item["index_id"] == index_id), None)
        if output is None:
            return

        if output["output_type"] == "temp_hum_control":
            temperature = to_float(get_gcode_param(cmd, "S"))
            wait = to_int(get_gcode_param(cmd, "W")) == 1
            self._set_temperature(index_id, temperature, wait)
            comm_instance._log(f"Setting thermostat output {index_id} to value {temperature}")
        else:
            reply = self._executor.run_enc_command(index_id, cmd, wait=True)
            if reply is not None:
                self._update_ui()
                comm_instance._log(reply)
