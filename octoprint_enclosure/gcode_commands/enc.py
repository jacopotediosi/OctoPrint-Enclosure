from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import clamp, get_gcode_param, to_float, to_int

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
        if output_type == "regular":
            value = clamp(to_int(get_gcode_param(cmd, "S")), 0, 1) == 1
            if output["active_low"]:
                value = not value
            if output["gpio_i2c_enabled"]:
                plugin.gpio_i2c_write(output, value)
            else:
                plugin.write_gpio(to_int(output["gpio_pin"]), value)
            comm_instance._log(f"Setting REGULAR output {index_id} to value {value}")
        elif output_type == "pwm":
            duty_cycle = clamp(to_int(get_gcode_param(cmd, "S")), 0, 100)
            output["duty_cycle"] = duty_cycle
            plugin.write_pwm(to_int(output["gpio_pin"]), duty_cycle)
            comm_instance._log(f"Setting PWM output {index_id} to value {duty_cycle}")
        elif output_type in ("neopixel_indirect", "neopixel_direct"):
            red, green, blue = (get_gcode_param(cmd, letter) for letter in "RGB")
            plugin.send_neopixel_command(output, red, green, blue)
            comm_instance._log(f"Setting NEOPIXEL output {index_id} to red: {red} green: {green} blue: {blue}")
        elif output_type == "temp_hum_control":
            temperature = to_float(get_gcode_param(cmd, "S"))
            if to_int(get_gcode_param(cmd, "W")) == 1 and plugin._printer.is_printing():
                plugin._printer.pause_print()
                plugin.waiting_temperature.append(index_id)
            output["temp_ctr_set_value"] = temperature
            plugin.update_ui_set_temperature()
            plugin.handle_temp_hum_control()
            comm_instance._log(f"Setting TEMP/HUM control output {index_id} to value {temperature}")
