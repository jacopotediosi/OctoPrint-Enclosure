from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from octoprint.plugin import PluginSettings


def migrate_settings(target: int, current: int | None, settings: PluginSettings, logger: logging.Logger) -> None:
    """Bring the stored settings up to a newer settings version.

    Args:
        target (int): The settings version to migrate to.
        current (int | None): The settings version in storage, or None if it was never written.
        settings (PluginSettings): The settings to migrate, updated in place.
        logger (logging.Logger): The logger to write to.

    """
    logger.warning(
        "######### current settings version %s target settings version %s #########",
        current,
        target,
    )
    logger.info("#########        Current settings        #########")
    logger.info("rpi_outputs: %s", settings.get(["rpi_outputs"]))
    logger.info("rpi_inputs: %s", settings.get(["rpi_inputs"]))
    logger.info("#########        End Current Settings        #########")
    if current >= 4 and target == 10:
        logger.warning("######### migrating settings to v10 #########")
        old_outputs = settings.get(["rpi_outputs"])
        old_inputs = settings.get(["rpi_inputs"])
        for rpi_output in old_outputs:
            if "shutdown_on_failed" not in rpi_output:
                rpi_output["shutdown_on_failed"] = False
            if "shell_script" not in rpi_output:
                rpi_output["shell_script"] = ""
            if "gpio_i2c_enabled" not in rpi_output:
                rpi_output["gpio_i2c_enabled"] = False
            if "gpio_i2c_bus" not in rpi_output:
                rpi_output["gpio_i2c_bus"] = 1
            if "gpio_i2c_address" not in rpi_output:
                rpi_output["gpio_i2c_address"] = 1
            if "gpio_i2c_register" not in rpi_output:
                rpi_output["gpio_i2c_register"] = 1
            if "gpio_i2c_data_on" not in rpi_output:
                rpi_output["gpio_i2c_data_on"] = 1
            if "gpio_i2c_data_off" not in rpi_output:
                rpi_output["gpio_i2c_data_off"] = 0
            if "gpio_i2c_register_status" not in rpi_output:
                rpi_output["gpio_i2c_register_status"] = 1
            if "shutdown_on_error" not in rpi_output:
                rpi_output["shutdown_on_error"] = False
        settings.set(["rpi_outputs"], old_outputs)

        old_inputs = settings.get(["rpi_inputs"])
        for rpi_input in old_inputs:
            if "temp_i2c_bus" not in rpi_input:
                rpi_input["temp_i2c_bus"] = 1
            if "temp_i2c_address" not in rpi_input:
                rpi_input["temp_i2c_address"] = 1
            if "temp_i2c_register" not in rpi_input:
                rpi_input["temp_i2c_register"] = 1
            if "show_graph_temp" not in rpi_input:
                rpi_input["show_graph_temp"] = False
            if "show_graph_humidity" not in rpi_input:
                rpi_input["show_graph_humidity"] = False
        settings.set(["rpi_inputs"], old_inputs)
    else:
        logger.warning("######### settings not compatible #########")
        settings.set(["rpi_outputs"], [])
        settings.set(["rpi_inputs"], [])
