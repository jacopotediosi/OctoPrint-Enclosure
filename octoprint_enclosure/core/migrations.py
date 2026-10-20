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

    rpi_outputs = settings.get(["rpi_outputs"])
    rpi_inputs = settings.get(["rpi_inputs"])
    actions = settings.get(["actions"])
    automations = settings.get(["automations"])

    logger.info("Old settings:")
    logger.info("rpi_outputs: %s", rpi_outputs)
    logger.info("rpi_inputs: %s", rpi_inputs)
    logger.info("actions: %s", actions)
    logger.info("automations: %s", automations)

    current = 0 if current is None else current

    if current < 10:
        logger.warning("Migrating settings to v10")

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

    if current < 11:
        logger.warning("Migrating settings to v11")

        # Up to version 10, the G-code and shell script actions were saved among the outputs. From version 11, they are
        # saved in the actions key, with the same keys and id, and their type is in action_type instead of output_type.
        action_types = ("gcode_output", "shell_output")
        actions = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") in action_types]
        rpi_outputs = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") not in action_types]
        for action in actions:
            action["action_type"] = action.pop("output_type")

        # Up to version 10, the controlled_io_set_value key stored the electrical level to write on the controlled
        # output: "low", "high" or "toggle". With an active low output, "low" meant on, which was confusing.
        # From version 11, the controlled_io_set_state key stores what to do instead: "on", "off" or "toggle".
        # The new value comes from the old level and from the active_low of the output.
        active_low_by_id = {to_int(output.get("index_id")): bool(output.get("active_low")) for output in rpi_outputs}
        for item_settings in [*rpi_inputs, *rpi_outputs]:
            set_value = item_settings.pop("controlled_io_set_value", "low")
            if set_value == "toggle":
                set_state = "toggle"
            else:
                high = set_value != "low"
                active_low = active_low_by_id.get(to_int(item_settings.get("controlled_io")), False)
                set_state = "on" if high != active_low else "off"
            item_settings["controlled_io_set_state"] = set_state
        for action in actions:
            action.pop("controlled_io_set_value", None)

        # Up to version 10, a GPIO input also stored what it triggers, with its type in action_type. From version 11,
        # each GPIO input gets an automation in the automations key, with a new id, the label of the input, and the
        # keys moved from the input. The automation is a "rule": its trigger_type is "gpio_input", with the id of the
        # input in input, and its reaction_type is the old action_type. A rule that runs an action gets the
        # "run_action" reaction_type instead of "output_control", with the id of the action in action instead of
        # controlled_io. A filament sensor gets the "filament" automation_type instead, and 0 in filament_sensor_timeout
        # if the key is empty or missing, as it was read up to version 10. A GPIO input that controls nothing, that is
        # an output_control with an empty controlled_io as new inputs had by default, gets no automation.
        moved_keys = (
            "edge",
            "controlled_io",
            "controlled_io_set_state",
            "printer_action",
            "filament_sensor_enabled",
            "filament_sensor_timeout",
        )
        action_ids = {to_int(action.get("index_id")) for action in actions}
        next_automation_id = max((to_int(item.get("index_id")) for item in [*rpi_outputs, *actions]), default=0) + 1
        automations = []
        for rpi_input in rpi_inputs:
            action_type = rpi_input.pop("action_type", "")
            moved = {key: rpi_input.pop(key) for key in moved_keys if key in rpi_input}
            if rpi_input.get("input_type") != "gpio":
                continue
            if action_type == "output_control" and moved.get("controlled_io") in ("", None):
                continue
            is_filament = action_type == "printer_control" and moved.get("printer_action") == "filament"
            automation = {
                "index_id": next_automation_id,
                "label": rpi_input.get("label"),
                "automation_type": "filament" if is_filament else "rule",
                "trigger_type": "gpio_input",
                "input": rpi_input.get("index_id"),
                "reaction_type": action_type,
                "action": "",
                **moved,
            }
            if action_type == "output_control" and to_int(moved.get("controlled_io")) in action_ids:
                automation["reaction_type"] = "run_action"
                automation["action"] = automation["controlled_io"]
                automation["controlled_io"] = ""
            if is_filament and automation.get("filament_sensor_timeout") in ("", None):
                automation["filament_sensor_timeout"] = 0
            automations.append(automation)
            next_automation_id += 1

        # Up to version 10, the global neopixel_dma key stored the DMA channel of all the NeoPixels connected directly
        # to the Raspberry Pi. From version 11, each output has its own neopixel_dma key with the same value.
        neopixel_dma = settings.get_int(["neopixel_dma"])
        for rpi_output in rpi_outputs:
            rpi_output["neopixel_dma"] = 10 if neopixel_dma is None else neopixel_dma
        settings.remove(["neopixel_dma"])

        # Up to version 10, the global use_sudo key chose whether the scripts of the sensors and of the NeoPixels ran
        # with sudo. From version 11, the plugin decides it by itself, and the key is removed.
        settings.remove(["use_sudo"])

    settings.set(["rpi_outputs"], rpi_outputs)
    settings.set(["rpi_inputs"], rpi_inputs)
    settings.set(["actions"], actions)
    settings.set(["automations"], automations)

    logger.info("Migrated settings:")
    logger.info("rpi_outputs: %s", rpi_outputs)
    logger.info("rpi_inputs: %s", rpi_inputs)
    logger.info("actions: %s", actions)
    logger.info("automations: %s", automations)
