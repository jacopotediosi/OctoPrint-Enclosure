from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.outputs import OutputError
from octoprint_enclosure.utils import get_gcode_param, to_float, to_int

if TYPE_CHECKING:
    from octoprint.util.comm import MachineCom

    from octoprint_enclosure.plugin import EnclosurePlugin


class EncHandler:
    """Handles the ENC G-code commands."""

    def __init__(self, plugin: EnclosurePlugin) -> None:
        """Set up the handler.

        Args:
            plugin (EnclosurePlugin): The plugin instance.

        """
        self._plugin = plugin

    def handle(self, comm_instance: MachineCom, cmd: str) -> None:
        """Run a G-code line, if it is an ENC command.

        Args:
            comm_instance (MachineCom): The connection to the printer, whose terminal the replies are written to.
            cmd (str): The G-code line.

        """
        plugin = self._plugin
        if not plugin._enclosure_settings.gcode_control or not cmd.strip().startswith("ENC"):
            return

        plugin._logger.debug("Received ENC command: %s", cmd)

        index_id = to_int(get_gcode_param(cmd, "O"))
        output = next((item for item in plugin.rpi_outputs if item["index_id"] == index_id), None)
        if output is None:
            return

        output_type = output["output_type"]
        if output_type == "temp_hum_control":
            temperature = to_float(get_gcode_param(cmd, "S"))
            if to_int(get_gcode_param(cmd, "W")) == 1 and plugin._printer.is_printing():
                plugin._printer.pause_print()
                plugin.waiting_temperature.add(index_id)
            plugin.set_temp_hum_control_target(index_id, temperature)
            plugin.update_ui_set_temperature()
            plugin.handle_temp_hum_control()
            comm_instance._log(f"Setting TEMP/HUM control output {index_id} to value {temperature}")
        else:
            try:
                reply = plugin._outputs.run_enc_command(index_id, cmd)
            except OutputError as error:
                plugin._logger.debug("Can't run ENC command %s: %s", cmd, error)
                return
            except Exception:
                plugin._logger.exception("Error running ENC command: %s", cmd)
                return
            if reply is not None:
                plugin.update_ui()
                comm_instance._log(reply)
