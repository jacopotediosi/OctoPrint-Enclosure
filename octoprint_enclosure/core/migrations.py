from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import to_int

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
    logger = logger.getChild("Migration")
    logger.warning("Start migration from %s to %s", current, target)

    rpi_inputs = settings.get(["rpi_inputs"])
    rpi_outputs = settings.get(["rpi_outputs"])

    logger.info("Old settings:")
    logger.info("rpi_inputs: %s", rpi_inputs)
    logger.info("rpi_outputs: %s", rpi_outputs)

    current = 0 if current is None else current

    if current < 10:
        logger.warning("Migrating settings to v10")

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

    if current < 11:
        logger.warning("Migrating settings to v11")

        # Up to version 10, the controlled_io_set_value key stored the electrical level to write on the controlled
        # output: "low", "high" or "toggle". With an active low output, "low" meant on, which was confusing.
        # From version 11, the controlled_io_set_state key stores what to do instead: "on", "off" or "toggle".
        # The new value comes from the old level and from the active_low of the output, so nothing changes.
        # The old key stays, for users who go back to the previous version.
        active_low_by_id = {to_int(output.get("index_id")): bool(output.get("active_low")) for output in rpi_outputs}
        for item_settings in [*rpi_inputs, *rpi_outputs]:
            set_value = item_settings.get("controlled_io_set_value", "low")
            if set_value == "toggle":
                set_state = "toggle"
            else:
                high = set_value != "low"
                active_low = active_low_by_id.get(to_int(item_settings.get("controlled_io")), False)
                set_state = "on" if high != active_low else "off"
            item_settings["controlled_io_set_state"] = set_state

        # Up to version 10, the global neopixel_dma key stored the DMA channel of all the NeoPixels connected directly
        # to the Raspberry Pi. From version 11, each output has its own neopixel_dma key, with the same value.
        # The global key stays, for users who go back to the previous version.
        neopixel_dma = settings.get_int(["neopixel_dma"])
        for rpi_output in rpi_outputs:
            rpi_output["neopixel_dma"] = 10 if neopixel_dma is None else neopixel_dma

    settings.set(["rpi_inputs"], rpi_inputs)
    settings.set(["rpi_outputs"], rpi_outputs)

    logger.info("Migrated settings:")
    logger.info("rpi_inputs: %s", rpi_inputs)
    logger.info("rpi_outputs: %s", rpi_outputs)
