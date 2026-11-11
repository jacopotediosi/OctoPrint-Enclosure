"""Add the keys introduced in version 10 to the inputs and outputs saved by an older version.

Inputs get the keys of an I2C sensor (`temp_i2c_*`) and the graph switches `show_graph_temp` and `show_graph_humidity`.
Outputs get the keys of a relay on an I2C expander (`gpio_i2c_*`), `shell_script`, `shutdown_on_failed` and
`shutdown_on_error`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from octoprint.plugin import PluginSettings


def migrate(settings: PluginSettings, logger: logging.Logger) -> None:
    """Migrate the settings to version 10.

    Args:
        settings (PluginSettings): The settings to migrate, updated in place.
        logger (logging.Logger): The logger to write to.

    """
    logger = logger.getChild("v10")

    rpi_inputs = settings.get(["rpi_inputs"])
    rpi_outputs = settings.get(["rpi_outputs"])

    new_input_defaults = {
        "temp_i2c_bus": 1,
        "temp_i2c_address": 1,
        "temp_i2c_register": 1,
        "show_graph_temp": False,
        "show_graph_humidity": False,
    }
    for rpi_input in rpi_inputs:
        for key, value in new_input_defaults.items():
            rpi_input.setdefault(key, value)

    new_output_defaults = {
        "shutdown_on_failed": False,
        "shell_script": "",
        "gpio_i2c_enabled": False,
        "gpio_i2c_bus": 1,
        "gpio_i2c_address": 1,
        "gpio_i2c_register": 1,
        "gpio_i2c_data_on": 1,
        "gpio_i2c_data_off": 0,
        "gpio_i2c_register_status": 1,
        "shutdown_on_error": False,
    }
    for rpi_output in rpi_outputs:
        for key, value in new_output_defaults.items():
            rpi_output.setdefault(key, value)

    settings.set(["rpi_inputs"], rpi_inputs)
    settings.set(["rpi_outputs"], rpi_outputs)
