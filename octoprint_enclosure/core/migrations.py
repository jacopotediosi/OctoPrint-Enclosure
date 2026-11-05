from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import is_rgb, parse_hhmm, parse_rgb, to_float, to_int

from .measurement import TemperatureUnit

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

        # Up to version 10, the plugin saved into settings some runtime-only values by mistake.
        input_runtime_keys = ("temp_sensor_temp", "temp_sensor_humidity")
        for rpi_input in rpi_inputs:
            for key in input_runtime_keys:
                rpi_input.pop(key, None)
        output_runtime_keys = (
            "gpio_status",
            "duty_cycle",
            "new_duty_cycle",
            "pwm_status",
            "neopixel_color",
            "new_neopixel_color",
            "ledstrip_color",
            "new_ledstrip_color",
            "temp_ctr_set_value",
            "temp_ctr_new_set_value",
        )
        for rpi_output in rpi_outputs:
            for key in output_runtime_keys:
                rpi_output.pop(key, None)

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
        next_action_id = max(action_ids, default=0) + 1
        next_automation_id = 1
        automations: list[dict] = []
        # The printer action stop_temp_hum_control turned off the thermostats with auto_shutdown on when it ran. It
        # becomes a rule that turns off every heater and every other thermostat with auto_shutdown on at migration time.
        stopped_thermostats = [
            rpi_output.get("index_id")
            for rpi_output in rpi_outputs
            if rpi_output.get("output_type") == "temp_hum_control"
            and (rpi_output.get("temp_ctr_type") == "heater" or rpi_output.get("auto_shutdown"))
        ]
        for rpi_input in rpi_inputs:
            moved = {key: rpi_input.pop(key) for key in input_keys if key in rpi_input}
            action_type = moved.get("action_type", "")
            printer_action = moved.get("printer_action", "")
            if rpi_input.get("input_type") != "gpio":
                continue
            if action_type == "output_control" and moved.get("controlled_io") in ("", None):
                continue
            if (
                action_type == "printer_control"
                and printer_action == "stop_temp_hum_control"
                and not stopped_thermostats
            ):
                continue

            automation = {
                "index_id": next_automation_id,
                "label": rpi_input.get("label"),
                "automation_type": "rule",
                "trigger_type": "gpio_input",
                "input": rpi_input.get("index_id"),
            }
            next_automation_id += 1
            if "edge" in moved:
                automation["edge"] = moved["edge"]

            reaction = {}
            reactions = [reaction]
            if action_type == "printer_control" and printer_action == "filament":
                # A filament sensor is an automation of its own type, not a rule
                automation["automation_type"] = "filament"
                if "filament_sensor_enabled" in moved:
                    automation["enabled"] = moved["filament_sensor_enabled"]
                if "filament_sensor_timeout" in moved:
                    automation["filament_sensor_timeout"] = moved["filament_sensor_timeout"]
            elif action_type == "printer_control" and printer_action == "stop_temp_hum_control":
                reactions = [
                    {"reaction_type": "output_control", "controlled_io": index_id, "controlled_io_set_state": "off"}
                    for index_id in stopped_thermostats
                ]
            elif action_type == "printer_control":
                # A printer command becomes a new action, that the rule runs
                reaction["reaction_type"] = "run_action"
                reaction["action"] = next_action_id
                actions.append(
                    {
                        "index_id": next_action_id,
                        "label": rpi_input.get("label"),
                        "action_type": "printer",
                        "printer_action": printer_action,
                        "hide_btn_ui": True,
                        "show_on_navbar": False,
                    },
                )
                next_action_id += 1
            elif action_type == "output_control" and to_int(moved.get("controlled_io")) in action_ids:
                # The G-code and shell script actions were outputs, so a GPIO input could control them like outputs
                reaction["reaction_type"] = "run_action"
                reaction["action"] = moved["controlled_io"]
            else:
                reaction["reaction_type"] = action_type
                for key in ("controlled_io", "controlled_io_set_state"):
                    if key in moved:
                        reaction[key] = moved[key]
            automation["reactions"] = reactions
            automations.append(automation)

        # A temperature alarm moves to the automations, with a new id and its keys, as a rule that sets controlled_io at
        # every reading of linked_temp_sensor above alarm_set_temp.
        temperature_alarms = [
            rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") == "temperature_alarm"
        ]
        rpi_outputs = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") != "temperature_alarm"]
        for alarm in temperature_alarms:
            # An alarm whose alarm_set_temp was 0 was off and did nothing, so it is dropped
            if int(to_float(alarm.get("alarm_set_temp"))) == 0:
                continue
            del alarm["output_type"]
            alarm["index_id"] = next_automation_id
            next_automation_id += 1
            alarm.update({"automation_type": "rule", "trigger_type": "temperature", "repeat_while_above": True})
            reaction = {"reaction_type": "output_control"}
            for key in ("controlled_io", "controlled_io_set_state"):
                if key in alarm:
                    reaction[key] = alarm.pop(key)
            alarm["reactions"] = [reaction]
            automations.append(alarm)

        # A PWM with pwm_temperature_linked on stored the line of its duty cycle. The line moves to a new
        # "pwm_temperature_linked" automation, with a new id and the label of the output, that drives the PWM in output.
        for rpi_output in rpi_outputs:
            if rpi_output.get("output_type") != "pwm" or not rpi_output.get("pwm_temperature_linked"):
                continue
            del rpi_output["pwm_temperature_linked"]
            automation = {
                "index_id": next_automation_id,
                "label": rpi_output.get("label"),
                "automation_type": "pwm_temperature_linked",
                "output": rpi_output.get("index_id"),
            }
            next_automation_id += 1
            for key in ("linked_temp_sensor", "temperature_a", "duty_a", "temperature_b", "duty_b"):
                if key in rpi_output:
                    automation[key] = rpi_output.pop(key)
            automations.append(automation)

        # Up to version 10, each sensor had its own unit (via `use_fahrenheit`), and the plugin stored temperatures in
        # that unit. From version 11 onwards, the plugin uses a single, centralized `temperature_unit` setting, which
        # determines how temperatures are converted for the frontend, while on the backend, they are always handled
        # exclusively in Celsius.
        fahrenheit_sensor_ids = set()
        celsius_sensor_ids = set()
        for rpi_input in rpi_inputs:
            use_fahrenheit = bool(rpi_input.pop("use_fahrenheit", False))
            if rpi_input.get("input_type") != "temperature_sensor":
                continue
            if use_fahrenheit:
                fahrenheit_sensor_ids.add(to_int(rpi_input.get("index_id")))
            else:
                celsius_sensor_ids.add(to_int(rpi_input.get("index_id")))
        new_unit_should_be_fahrenheit = len(fahrenheit_sensor_ids) > len(celsius_sensor_ids)
        settings.set(
            ["temperature_unit"],
            (TemperatureUnit.FAHRENHEIT if new_unit_should_be_fahrenheit else TemperatureUnit.CELSIUS).value,
        )
        fahrenheit = TemperatureUnit.FAHRENHEIT
        for rpi_output in rpi_outputs:
            is_temperature_thermostat = (
                rpi_output.get("output_type") == "temp_hum_control"
                and rpi_output.get("temp_ctr_type") != "dehumidifier"
            )
            if (
                not is_temperature_thermostat
                or to_int(rpi_output.get("linked_temp_sensor")) not in fahrenheit_sensor_ids
            ):
                continue
            if to_float(rpi_output.get("temp_ctr_default_value")) != 0:
                rpi_output["temp_ctr_default_value"] = fahrenheit.to_celsius(
                    to_float(rpi_output.get("temp_ctr_default_value")),
                )
            rpi_output["temp_ctr_deadband"] = fahrenheit.to_celsius_interval(
                to_float(rpi_output.get("temp_ctr_deadband")),
            )
            if to_float(rpi_output.get("temp_ctr_max_temp")) > 0:
                rpi_output["temp_ctr_max_temp"] = fahrenheit.to_celsius(to_float(rpi_output.get("temp_ctr_max_temp")))
        for automation in automations:
            if to_int(automation.get("linked_temp_sensor")) not in fahrenheit_sensor_ids:
                continue
            if automation.get("automation_type") == "pwm_temperature_linked":
                for key in ("temperature_a", "temperature_b"):
                    automation[key] = fahrenheit.to_celsius(to_float(automation.get(key)))
            elif automation.get("trigger_type") == "temperature" and to_float(automation.get("alarm_set_temp")) != 0:
                automation["alarm_set_temp"] = fahrenheit.to_celsius(to_float(automation.get("alarm_set_temp")))

        # Up to version 10, the outputs had the keys "auto_startup", "startup_with_server", "auto_shutdown",
        # "shutdown_on_failed" and "shutdown_on_error", that turned the output on and off by themselves in some
        # situations. Now each of them becomes an automation rule on the OctoPrint events with a reaction on the output.
        # "auto_startup" and "auto_shutdown" become a rule for every output, enabled or disabled as the key was;
        # "startup_with_server", "shutdown_on_failed" and "shutdown_on_error" become a rule only if the key was on. The
        # rules on PWM, LED strip, NeoPixel and thermostat outputs take the setpoint from the default of the output:
        # without one, and for a PWM driven by a curve, the rule is not created.
        def add_rule(rpi_output, events, state, *, enabled, time=0, printing=None, setpoint=None):
            nonlocal next_automation_id

            # startup_time and shutdown_time held seconds, or a time of day as HH:MM
            time_of_day = parse_hhmm(str(time))
            delay = 0 if time_of_day is not None else max(to_float(time), 0)
            at = time_of_day.strftime("%H:%M") if time_of_day is not None else ""

            conditions = []
            if printing is not None and (delay > 0 or at):
                conditions.append({"condition_type": "print_job", "printing": printing})

            label_suffixes = {
                ("PrintStarted",): "at print start",
                ("PrintDone",): "at print end",
                ("PrintDone", "PrintCancelled", "PrintFailed"): "at print end",
                ("PrintCancelled", "PrintFailed"): "on print failure",
                ("Error", "Disconnected"): "on printer error",
                ("Startup",): "at server start",
            }

            automations.append(
                {
                    "index_id": next_automation_id,
                    "label": f"Turn {state} {rpi_output.get('label')} {label_suffixes.get(tuple(events), '')}".strip(),
                    "automation_type": "rule",
                    "enabled": enabled,
                    "trigger_type": "octoprint_event",
                    "octoprint_events": events,
                    "delay": delay,
                    "at": at,
                    "conditions": conditions,
                    "reactions": [
                        {
                            "reaction_type": "output_control",
                            "controlled_io": rpi_output.get("index_id"),
                            "controlled_io_set_state": state,
                            **(setpoint or {}),
                        },
                    ],
                },
            )
            next_automation_id += 1

        pwm_temperature_linked_ids = {
            to_int(automation.get("output"))
            for automation in automations
            if automation.get("automation_type") == "pwm_temperature_linked"
        }

        for rpi_output in rpi_outputs:
            output_type = rpi_output.get("output_type")

            on_setpoint: dict | None = {}
            if output_type == "pwm":
                duty_cycle = to_float(rpi_output.get("default_duty_cycle"))
                on_setpoint = {"duty_cycle": duty_cycle} if duty_cycle > 0 else None
            elif output_type in ("ledstrip", "neopixel_direct", "neopixel_indirect"):
                color_key = "default_ledstrip_color" if output_type == "ledstrip" else "default_neopixel_color"
                color = str(rpi_output.get(color_key, ""))
                red, green, blue = (to_int(part) for part in parse_rgb(color)) if is_rgb(color) else (0, 0, 0)
                on_setpoint = {"color": f"#{red:02x}{green:02x}{blue:02x}"} if (red, green, blue) != (0, 0, 0) else None
            elif output_type == "temp_hum_control":
                target = to_float(rpi_output.get("temp_ctr_default_value"))
                on_setpoint = {"target": target} if target != 0 else None
            if to_int(rpi_output.get("index_id")) in pwm_temperature_linked_ids:
                on_setpoint = None

            if on_setpoint is not None:
                add_rule(
                    rpi_output,
                    ["PrintStarted"],
                    "on",
                    enabled=bool(rpi_output.get("auto_startup")),
                    time=rpi_output.get("startup_time", 0),
                    printing=True,
                    setpoint=on_setpoint,
                )

            end_events = ["PrintDone"]
            if rpi_output.get("shutdown_on_failed") and output_type != "temp_hum_control":
                end_events += ["PrintCancelled", "PrintFailed"]

            add_rule(
                rpi_output,
                end_events,
                "off",
                enabled=bool(rpi_output.get("auto_shutdown")),
                time=rpi_output.get("shutdown_time", 0),
                printing=False,
            )

            if rpi_output.get("shutdown_on_failed") and output_type == "temp_hum_control":
                add_rule(
                    rpi_output,
                    ["PrintCancelled", "PrintFailed"],
                    "off",
                    enabled=bool(rpi_output.get("auto_shutdown")),
                )

            if rpi_output.get("shutdown_on_error"):
                add_rule(rpi_output, ["Error", "Disconnected"], "off", enabled=True)

            if rpi_output.get("startup_with_server") and on_setpoint is not None:
                add_rule(rpi_output, ["Startup"], "on", enabled=True, setpoint=on_setpoint)

        # Up to version 10, every output held the keys of every type of item. The outputs that remain lose the keys of
        # actions, alarms, PWM curves and automatic fields; the actions and the automations keep only the keys of their
        # type.
        moved_keys = (
            "gcode",
            "shell_script",
            "alarm_set_temp",
            "controlled_io",
            "controlled_io_set_state",
            "pwm_temperature_linked",
            "temperature_a",
            "duty_a",
            "temperature_b",
            "duty_b",
            "auto_startup",
            "startup_time",
            "auto_shutdown",
            "shutdown_time",
            "shutdown_on_failed",
            "shutdown_on_error",
            "startup_with_server",
        )
        for rpi_output in rpi_outputs:
            for key in moved_keys:
                rpi_output.pop(key, None)
        action_keys = {
            "index_id",
            "label",
            "action_type",
            "gcode",
            "shell_script",
            "printer_action",
            "hide_btn_ui",
            "show_on_navbar",
        }
        for action in actions:
            for key in set(action) - action_keys:
                del action[key]
        automation_keys = {
            "index_id",
            "label",
            "automation_type",
            "trigger_type",
            "input",
            "edge",
            "linked_temp_sensor",
            "alarm_set_temp",
            "repeat_while_above",
            "reactions",
            "octoprint_events",
            "delay",
            "at",
            "conditions",
            "enabled",
            "filament_sensor_timeout",
            "output",
            "temperature_a",
            "duty_a",
            "temperature_b",
            "duty_b",
        }
        for automation in automations:
            for key in set(automation) - automation_keys:
                del automation[key]

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
            "octoprint_events": [],
            "delay": 0,
            "at": "",
            "conditions": [],
            "enabled": True,
            "filament_sensor_timeout": 120,
            "output": "",
            "temperature_a": 0,
            "duty_a": 0,
            "temperature_b": 0,
            "duty_b": 0,
        }
        reaction_defaults = {
            "reaction_type": "output_control",
            "controlled_io": "",
            "controlled_io_set_state": "on",
            "duty_cycle": 0,
            "color": "",
            "target": 0,
            "action": "",
        }
        for automation in automations:
            for key, value in automation_defaults.items():
                automation.setdefault(key, value)
            automation.setdefault("reactions", [{}])
            for reaction in automation["reactions"]:
                for key, value in reaction_defaults.items():
                    reaction.setdefault(key, value)

        # Up to version 10, the global neopixel_dma key stored the DMA channel of all the NeoPixels connected directly
        # to the Raspberry Pi. From version 11, each output has its own neopixel_dma key with the same value.
        neopixel_dma = settings.get_int(["neopixel_dma"])
        for rpi_output in rpi_outputs:
            rpi_output["neopixel_dma"] = 10 if neopixel_dma is None else neopixel_dma
        settings.remove(["neopixel_dma"])

        # Up to version 10, the global use_sudo key chose whether the scripts of the sensors and of the NeoPixels ran
        # with sudo. From version 11, the plugin decides it by itself, and the key is removed.
        settings.remove(["use_sudo"])

        # Up to version 10, the global setting use_board_pin_number chose whether the GPIO pins were numbered by their
        # position on the header (BOARD) instead of by their BCM number. From version 11 every pin is a BCM number, so
        # the BOARD numbers need to be converted.
        if settings.get_boolean(["use_board_pin_number"]):
            # The pin_to_gpio_rev3 table of RPi.GPIO (source/common.c)
            board_to_bcm = {
                3: 2, 5: 3, 7: 4, 8: 14, 10: 15, 11: 17, 12: 18, 13: 27, 15: 22, 16: 23, 18: 24, 19: 10, 21: 9,
                22: 25, 23: 11, 24: 8, 26: 7, 29: 5, 31: 6, 32: 12, 33: 13, 35: 19, 36: 16, 37: 26, 38: 20, 40: 21,
            }  # fmt: skip
            for rpi_input in rpi_inputs:
                pin = to_int(rpi_input.get("gpio_pin"))
                if rpi_input.get("input_type") == "gpio" and pin > 0:
                    rpi_input["gpio_pin"] = board_to_bcm.get(pin, "")
            for rpi_output in rpi_outputs:
                output_type = rpi_output.get("output_type")
                is_switch = output_type in ("regular", "temp_hum_control")
                uses_pin = output_type == "pwm" or (is_switch and not rpi_output.get("gpio_i2c_enabled"))
                pin = to_int(rpi_output.get("gpio_pin"))
                if uses_pin and pin > 0:
                    rpi_output["gpio_pin"] = board_to_bcm.get(pin, "")
        settings.remove(["use_board_pin_number"])

    settings.set(["rpi_inputs"], rpi_inputs)
    settings.set(["rpi_outputs"], rpi_outputs)
    settings.set(["actions"], actions)
    settings.set(["automations"], automations)

    logger.info("Migrated settings:")
    logger.info("rpi_inputs: %s", rpi_inputs)
    logger.info("rpi_outputs: %s", rpi_outputs)
    logger.info("actions: %s", actions)
    logger.info("automations: %s", automations)
