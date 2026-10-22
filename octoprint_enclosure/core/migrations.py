from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import to_float, to_int

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
    actions = settings.get(["actions"])
    automations = settings.get(["automations"])

    logger.info("Old settings:")
    logger.info("rpi_inputs: %s", rpi_inputs)
    logger.info("rpi_outputs: %s", rpi_outputs)
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

        # Up to version 10, rpi_outputs and rpi_inputs also held what is neither an output nor an input. From version
        # 11, the actions list holds what runs when asked, and the automations list what decides by itself when to act.
        # The steps below move each of them to its list.

        # The G-code and shell script actions move from the outputs to the actions, with the same id and keys. Their
        # type moves from output_type to action_type.
        action_types = ("gcode_output", "shell_output")
        actions = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") in action_types]
        rpi_outputs = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") not in action_types]
        for action in actions:
            action["action_type"] = action.pop("output_type")

        # controlled_io_set_value, the electrical level to write on a controlled output ("low", "high" or "toggle"),
        # becomes controlled_io_set_state, what to do ("on", "off" or "toggle"). With active_low on, the level means the
        # opposite.
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

        # What a GPIO input triggers, with its type in action_type, moves to a new automation started by the input, with
        # a new id and the label of the input. A GPIO input that triggers nothing gets no automation.
        input_keys = (
            "action_type",
            "printer_action",
            "edge",
            "controlled_io",
            "controlled_io_set_state",
            "filament_sensor_enabled",
            "filament_sensor_timeout",
        )
        action_ids = {to_int(action.get("index_id")) for action in actions}
        next_id = max((to_int(item.get("index_id")) for item in [*rpi_outputs, *actions]), default=0) + 1
        automations = []
        for rpi_input in rpi_inputs:
            moved = {key: rpi_input.pop(key) for key in input_keys if key in rpi_input}
            action_type = moved.get("action_type", "")
            printer_action = moved.get("printer_action", "")
            if rpi_input.get("input_type") != "gpio":
                continue
            if action_type == "output_control" and moved.get("controlled_io") in ("", None):
                continue

            automation = {
                "index_id": next_id,
                "label": rpi_input.get("label"),
                "automation_type": "rule",
                "trigger_type": "gpio_input",
                "input": rpi_input.get("index_id"),
            }
            next_id += 1
            if "edge" in moved:
                automation["edge"] = moved["edge"]

            if action_type == "printer_control" and printer_action == "filament":
                # A filament sensor is an automation of its own type, not a rule
                automation["automation_type"] = "filament"
                for key in ("filament_sensor_enabled", "filament_sensor_timeout"):
                    if key in moved:
                        automation[key] = moved[key]
            elif action_type == "printer_control" and printer_action == "stop_temp_hum_control":
                automation["reaction_type"] = "stop_temp_hum_control"
            elif action_type == "printer_control":
                # A printer command becomes a new action, that the rule runs
                automation["reaction_type"] = "run_action"
                automation["action"] = next_id
                actions.append(
                    {
                        "index_id": next_id,
                        "label": rpi_input.get("label"),
                        "action_type": "printer",
                        "printer_action": printer_action,
                        "hide_btn_ui": True,
                        "show_on_navbar": False,
                    },
                )
                next_id += 1
            elif action_type == "output_control" and to_int(moved.get("controlled_io")) in action_ids:
                # The G-code and shell script actions were outputs, so a GPIO input could control them like outputs
                automation["reaction_type"] = "run_action"
                automation["action"] = moved["controlled_io"]
            else:
                automation["reaction_type"] = action_type
                for key in ("controlled_io", "controlled_io_set_state"):
                    if key in moved:
                        automation[key] = moved[key]
            automations.append(automation)

        # A temperature alarm moves to the automations, with the same id and keys, as a rule that sets controlled_io at
        # every reading of linked_temp_sensor above alarm_set_temp.
        alarms = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") == "temperature_alarm"]
        rpi_outputs = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") != "temperature_alarm"]
        for alarm in alarms:
            # An alarm whose alarm_set_temp was 0 was off and did nothing, so it is dropped
            if int(to_float(alarm.get("alarm_set_temp"))) == 0:
                continue
            del alarm["output_type"]
            alarm.update({"automation_type": "rule", "trigger_type": "temperature", "repeat_while_above": True})
            alarm["reaction_type"] = "output_control"
            automations.append(alarm)

        # A PWM with pwm_temperature_linked on stored the line of its duty cycle. The line moves to a new
        # "pwm_temperature_linked" automation, with a new id and the label of the output, that drives the PWM in output.
        for rpi_output in rpi_outputs:
            if rpi_output.get("output_type") != "pwm" or not rpi_output.get("pwm_temperature_linked"):
                continue
            del rpi_output["pwm_temperature_linked"]
            automation = {
                "index_id": next_id,
                "label": rpi_output.get("label"),
                "automation_type": "pwm_temperature_linked",
                "output": rpi_output.get("index_id"),
            }
            next_id += 1
            for key in ("linked_temp_sensor", "temperature_a", "duty_a", "temperature_b", "duty_b"):
                if key in rpi_output:
                    automation[key] = rpi_output.pop(key)
            automations.append(automation)

        # Up to version 10, these numbers were read as 0 when empty or missing. From version 11, numbers are read
        # strictly, so these get 0.
        number_keys_by_type = {
            "temp_hum_control": ("temp_ctr_deadband", "temp_ctr_max_temp"),
            "filament": ("filament_sensor_timeout",),
            "pwm_temperature_linked": ("temperature_a", "duty_a", "temperature_b", "duty_b"),
        }
        for item_settings in [*rpi_outputs, *automations]:
            item_type = item_settings.get("output_type") or item_settings.get("automation_type")
            for key in number_keys_by_type.get(item_type, ()):
                if item_settings.get(key) in ("", None):
                    item_settings[key] = 0

        # The settings page shows the keys of the type chosen for an action or an automation, and needs all of them to
        # change it: the missing ones get the defaults that the page gives to the new actions and automations.
        action_defaults = {"gcode": "", "shell_script": "", "printer_action": "pause"}
        for action in actions:
            for key, value in action_defaults.items():
                action.setdefault(key, value)
        automation_defaults = {
            "trigger_type": "gpio_input",
            "input": "",
            "edge": "fall",
            "linked_temp_sensor": "",
            "alarm_set_temp": "",
            "repeat_while_above": False,
            "reaction_type": "output_control",
            "controlled_io": "",
            "controlled_io_set_state": "on",
            "action": "",
            "filament_sensor_enabled": True,
            "filament_sensor_timeout": 120,
            "output": "",
            "temperature_a": 0,
            "duty_a": 0,
            "temperature_b": 0,
            "duty_b": 0,
        }
        for automation in automations:
            for key, value in automation_defaults.items():
                automation.setdefault(key, value)

        # Up to version 10, the global neopixel_dma key stored the DMA channel of all the NeoPixels connected directly
        # to the Raspberry Pi. From version 11, each output has its own neopixel_dma key with the same value.
        neopixel_dma = settings.get_int(["neopixel_dma"])
        for rpi_output in rpi_outputs:
            rpi_output["neopixel_dma"] = 10 if neopixel_dma is None else neopixel_dma
        settings.remove(["neopixel_dma"])

        # Up to version 10, the global use_sudo key chose whether the scripts of the sensors and of the NeoPixels ran
        # with sudo. From version 11, the plugin decides it by itself, and the key is removed.
        settings.remove(["use_sudo"])

    settings.set(["rpi_inputs"], rpi_inputs)
    settings.set(["rpi_outputs"], rpi_outputs)
    settings.set(["actions"], actions)
    settings.set(["automations"], automations)

    logger.info("Migrated settings:")
    logger.info("rpi_inputs: %s", rpi_inputs)
    logger.info("rpi_outputs: %s", rpi_outputs)
    logger.info("actions: %s", actions)
    logger.info("automations: %s", automations)
