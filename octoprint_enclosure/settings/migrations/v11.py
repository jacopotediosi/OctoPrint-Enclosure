"""Split the outputs list of version 10 into outputs, actions and automations.

Besides the real outputs, `rpi_outputs` held things that are not outputs. From version 11 it holds only the hardware,
and two lists are added, `actions` (run on request) and `automations` (act by themselves):
- G-code and shell scripts to run on demand become actions;
- temperature alarms, the temperature curves of the PWM outputs and the fields that switched an output on and off
  with the print become automations;
- what a GPIO input triggered, saved on the input in `rpi_inputs`, becomes an automation too.

The automations are new, and come in four types:
- "rule": a trigger (e.g., a GPIO edge, a temperature, an OctoPrint event), optional conditions (e.g., "print_job":
  only while printing) and reactions (e.g., "output_control": set an output; "run_action": run an action);
- "filament": a filament sensor that runs an action when the filament ends;
- "pwm_temperature_linked": the duty cycle of a PWM follows the temperature of a sensor;
- "toggle_timer": an output switches on and off in turn.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from octoprint_enclosure.utils import Rgb, TemperatureUnit, format_hex_color, parse_hhmm

if TYPE_CHECKING:
    import logging
    from typing import Any

    from octoprint.plugin import PluginSettings


def migrate(settings: PluginSettings, logger: logging.Logger) -> None:
    """Migrate the settings to version 11.

    Args:
        settings (PluginSettings): The settings to migrate, updated in place.
        logger (logging.Logger): The logger to write to.

    """
    logger = logger.getChild("v11")

    rpi_inputs = settings.get(["rpi_inputs"])
    rpi_outputs = settings.get(["rpi_outputs"])

    # The actions and the automations are new in version 11
    actions: list[dict] = []
    automations: list[dict] = []

    _remove_runtime_values_saved_by_mistake(rpi_inputs, rpi_outputs)
    _move_gcode_and_shell_outputs_to_actions(rpi_outputs, actions)
    _convert_controlled_io_level_to_state(rpi_inputs, rpi_outputs, actions)
    _convert_gpio_input_effects_to_automations(rpi_inputs, rpi_outputs, actions, automations)
    _move_filament_gcode_to_action(automations, actions, settings)
    _move_temperature_alarms_to_automations(rpi_outputs, automations)
    _move_pwm_temperature_curves_to_automations(rpi_outputs, automations)
    _move_toggle_timers_to_automations(rpi_outputs, automations)
    _replace_thermostat_no_maximum_temperature_with_null(rpi_outputs)
    _convert_temperatures_to_celsius(rpi_inputs, rpi_outputs, automations, settings)
    _convert_auto_startup_shutdown_to_automations(rpi_outputs, automations)
    _remove_keys_of_other_item_kinds(rpi_outputs, actions, automations)
    _replace_empty_numbers_with_zero(rpi_outputs, automations)
    _add_keys_of_every_type_with_defaults(actions, automations)
    _move_neopixel_dma_to_each_output(rpi_outputs, settings)
    _remove_use_sudo(settings)
    _convert_board_pins_to_bcm(rpi_inputs, rpi_outputs, settings)

    settings.set(["rpi_inputs"], rpi_inputs)
    settings.set(["rpi_outputs"], rpi_outputs)
    settings.set(["actions"], actions)
    settings.set(["automations"], automations)


def _new_id(items: list[dict]) -> int:
    """Return the next free id for `items`: the highest id plus one, or 1 if the list is empty."""
    return max((_to_int(item.get("index_id")) for item in items), default=0) + 1


def _to_float(value: Any) -> float:  # noqa: ANN401 - value is purposely untyped
    """Convert a value to float, or return 0 if it can't be converted."""
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _to_int(value: Any) -> int:  # noqa: ANN401 - value is purposely untyped
    """Convert a value to int, or return 0 if it can't be converted."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _remove_runtime_values_saved_by_mistake(rpi_inputs: list[dict], rpi_outputs: list[dict]) -> None:
    """Remove some runtime values that version 10 saved into the settings by mistake.

    E.g., the last sensor reading, the relay state, the PWM duty cycle, the LED color, the thermostat target, etc.
    From version 11 they live only in memory.
    """
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


def _move_gcode_and_shell_outputs_to_actions(rpi_outputs: list[dict], actions: list[dict]) -> None:
    """Move the G-code and shell script items from `rpi_outputs` to `actions`.

    A G-code or a shell script to run on demand used to be saved as an output, with `output_type` "gcode_output" or
    "shell_output". Each keeps its id and keys; `output_type` is renamed `action_type`, with the same value.
    """
    action_types = ("gcode_output", "shell_output")
    actions[:] = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") in action_types]
    rpi_outputs[:] = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") not in action_types]
    for action in actions:
        action["action_type"] = action.pop("output_type")


def _convert_controlled_io_level_to_state(rpi_inputs: list[dict], rpi_outputs: list[dict], actions: list[dict]) -> None:
    """Replace `controlled_io_set_value`, an electrical level, with `controlled_io_set_state`, on/off/toggle.

    What an input or a temperature alarm did to the output it controls used to be saved as the level to write on its
    pin: "low", "high" or "toggle". The new value, "on", "off" or "toggle", says what the user meant and does not
    depend on the wiring. On an output with `active_low` on, a level means the opposite state, so the conversion
    looks up the controlled output.
    """
    active_low_by_id = {_to_int(output.get("index_id")): bool(output.get("active_low")) for output in rpi_outputs}
    for item_settings in [*rpi_inputs, *rpi_outputs]:
        set_value = item_settings.pop("controlled_io_set_value", "low")
        if set_value == "toggle":
            set_state = "toggle"
        else:
            high = set_value != "low"
            active_low = active_low_by_id.get(_to_int(item_settings.get("controlled_io")), False)
            set_state = "on" if high != active_low else "off"
        item_settings["controlled_io_set_state"] = set_state
    for action in actions:
        action.pop("controlled_io_set_value", None)


def _convert_gpio_input_effects_to_automations(
    rpi_inputs: list[dict],
    rpi_outputs: list[dict],
    actions: list[dict],
    automations: list[dict],
) -> None:
    """Turn what each GPIO input triggered into an automation started by that input.

    The effect used to be saved on the input itself: `action_type` "output_control" with the output to control in
    `controlled_io`, or "printer_control" with the command to run in `printer_action` (pause, resume, filament change,
    "stop_temp_hum_control"). Now an input only reports the edges of its pin, and the effect is an automation with a
    new id and the label of the input:
    - a controlled output: an automation rule with an "output_control" reaction, or a "run_action" reaction when the
      output was a G-code or shell script item;
    - a printer command: an automation rule running a new "printer" action with that command;
    - "stop_temp_hum_control": an automation rule turning off every heater and, among the other thermostats, those whose
      `auto_shutdown` is on when the migration runs;
    - a filament sensor: a "filament" automation, enabled as the sensor was.
    """
    action_ids = {_to_int(action.get("index_id")) for action in actions}
    thermostat_ids_to_turn_off = [
        rpi_output.get("index_id")
        for rpi_output in rpi_outputs
        if rpi_output.get("output_type") == "temp_hum_control"
        and (rpi_output.get("temp_ctr_type") == "heater" or rpi_output.get("auto_shutdown"))
    ]

    for rpi_input in rpi_inputs:
        # Pop the input keys to move to automation rules
        action_type = rpi_input.pop("action_type", "")
        printer_action = rpi_input.pop("printer_action", "")
        edge = rpi_input.pop("edge", None)
        controlled_io = rpi_input.pop("controlled_io", None)
        controlled_io_set_state = rpi_input.pop("controlled_io_set_state", None)
        filament_sensor_enabled = rpi_input.pop("filament_sensor_enabled", None)
        rpi_input.pop("filament_sensor_timeout", None)

        if rpi_input.get("input_type") != "gpio":
            continue
        if action_type == "output_control" and controlled_io in ("", None):
            continue
        if (
            action_type == "printer_control"
            and printer_action == "stop_temp_hum_control"
            and not thermostat_ids_to_turn_off
        ):
            continue

        # Prepare the automation rule
        automation = {
            "index_id": _new_id(automations),
            "label": rpi_input.get("label"),
            "automation_type": "rule",
            "trigger_type": "gpio_input",
            "input": rpi_input.get("index_id"),
        }
        if edge is not None:
            automation["edge"] = edge

        # Prepare the automation rule reactions
        reaction = {}
        reactions = [reaction]
        if action_type == "printer_control" and printer_action == "filament":
            # Filament sensor
            automation["automation_type"] = "filament"
            automation["show_in_tab"] = True
            if filament_sensor_enabled is not None:
                automation["enabled"] = filament_sensor_enabled
        elif action_type == "printer_control" and printer_action == "stop_temp_hum_control":
            # stop_temp_hum_control
            reactions = [
                {"reaction_type": "output_control", "controlled_io": thermostat_id, "controlled_io_set_state": "off"}
                for thermostat_id in thermostat_ids_to_turn_off
            ]
        elif action_type == "printer_control":
            # Printer command
            printer_action_id = _new_id(actions)
            reaction["reaction_type"] = "run_action"
            reaction["action"] = printer_action_id
            actions.append(
                {
                    "index_id": printer_action_id,
                    "label": rpi_input.get("label"),
                    "action_type": "printer",
                    "printer_action": printer_action,
                    "hide_btn_ui": True,
                    "show_on_navbar": False,
                },
            )
        elif action_type == "output_control" and _to_int(controlled_io) in action_ids:
            # Output control of an item which was an output and now is an action (gcode, shell script)
            reaction["reaction_type"] = "run_action"
            reaction["action"] = controlled_io
        else:
            # Output control of a real output
            reaction["reaction_type"] = action_type
            if controlled_io is not None:
                reaction["controlled_io"] = controlled_io
            if controlled_io_set_state is not None:
                reaction["controlled_io_set_state"] = controlled_io_set_state
        automation["reactions"] = reactions

        # Append the automation rule
        automations.append(automation)


def _move_filament_gcode_to_action(automations: list[dict], actions: list[dict], settings: PluginSettings) -> None:
    """Turn the global filament change G-code into an action, and give it to every filament automation.

    Every filament sensor used to send the same global `filament_sensor_gcode`. Now each sensor runs an action chosen
    for it, so the G-code becomes a "Filament change" G-code action that every migrated sensor runs.
    """
    filament_automations = [automation for automation in automations if automation.get("automation_type") == "filament"]

    if filament_automations:
        action_id = _new_id(actions)

        gcode = settings.get(["filament_sensor_gcode"])
        if gcode is None:
            # A missing key means the G-code was never changed; use the default of version 10 then.
            gcode = (
                "G91  ;Set Relative Mode \n"
                "G1 E-5.000000 F500 ;Retract 5mm\n"
                "G1 Z15 F300         ;move Z up 15mm\n"
                "G90            ;Set Absolute Mode\n "
                "G1 X20 Y20 F9000      ;Move to hold position\n"
                "G91            ;Set Relative Mode\n"
                "G1 E-40 F500      ;Retract 40mm\n"
                "M0            ;Idle Hold\n"
                "G90            ;Set Absolute Mode\n"
                "G1 F5000         ;Set speed limits\n"
                "G28 X0 Y0         ;Home X Y\n"
                "M82            ;Set extruder to Absolute Mode\n"
                "G92 E0         ;Set Extruder to 0"
            )

        actions.append(
            {
                "index_id": action_id,
                "label": "Filament change",
                "action_type": "gcode_output",
                "gcode": gcode,
                "hide_btn_ui": True,
                "show_on_navbar": False,
            },
        )

        for automation in filament_automations:
            automation["action"] = action_id

    settings.remove(["filament_sensor_gcode"])


def _move_temperature_alarms_to_automations(rpi_outputs: list[dict], automations: list[dict]) -> None:
    """Move the temperature alarms from `rpi_outputs` to `automations`, as automation rules.

    An alarm was an output with `output_type` "temperature_alarm": on every reading of the sensor in
    `linked_temp_sensor` above `alarm_set_temp`, it set the output in `controlled_io`. It becomes an automation rule
    with a "temperature" trigger, which fires on every reading above the threshold, and an "output_control" reaction.
    """
    temperature_alarms = [
        rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") == "temperature_alarm"
    ]
    rpi_outputs[:] = [rpi_output for rpi_output in rpi_outputs if rpi_output.get("output_type") != "temperature_alarm"]

    for alarm in temperature_alarms:
        if int(_to_float(alarm.get("alarm_set_temp"))) == 0:
            # An alarm with alarm_set_temp 0 was disabled and is dropped
            continue

        del alarm["output_type"]
        alarm["index_id"] = _new_id(automations)
        alarm.update({"automation_type": "rule", "trigger_type": "temperature", "repeat_while_above": True})
        reaction = {"reaction_type": "output_control"}
        for key in ("controlled_io", "controlled_io_set_state"):
            if key in alarm:
                reaction[key] = alarm.pop(key)
        alarm["reactions"] = [reaction]
        automations.append(alarm)


def _move_pwm_temperature_curves_to_automations(rpi_outputs: list[dict], automations: list[dict]) -> None:
    """Move the temperature curve of the PWM outputs to automations.

    A PWM output with `pwm_temperature_linked` on used to set its own duty cycle during a print, interpolating between
    (`temperature_a`, `duty_a`) and (`temperature_b`, `duty_b`) on the sensor in `linked_temp_sensor`. That logic now
    lives in a "pwm_temperature_linked" automation, so the output holds only its hardware.
    """
    for rpi_output in rpi_outputs:
        if rpi_output.get("output_type") != "pwm" or not rpi_output.get("pwm_temperature_linked"):
            continue

        del rpi_output["pwm_temperature_linked"]
        automation = {
            "index_id": _new_id(automations),
            "label": rpi_output.get("label"),
            "automation_type": "pwm_temperature_linked",
            "conditions": [{"condition_type": "print_job", "printing": True}],
            "output": rpi_output.get("index_id"),
        }
        for key in ("linked_temp_sensor", "temperature_a", "duty_a", "temperature_b", "duty_b"):
            if key in rpi_output:
                automation[key] = rpi_output.pop(key)
        automations.append(automation)


def _move_toggle_timers_to_automations(rpi_outputs: list[dict], automations: list[dict]) -> None:
    """Move the toggle timer of the outputs to automations.

    A regular or PWM output with `toggle_timer` on used to cycle on and off during a print, for `toggle_timer_on` and
    `toggle_timer_off` seconds, and the tab showed a "Time Toggle" badge. The cycle now lives in a "toggle_timer"
    automation, so the output holds only its hardware.
    """
    for rpi_output in rpi_outputs:
        if rpi_output.get("output_type") not in ("regular", "pwm") or not rpi_output.get("toggle_timer"):
            continue

        automation = {
            "index_id": _new_id(automations),
            "label": f"Toggle {rpi_output.get('label')} while printing",
            "automation_type": "toggle_timer",
            "show_in_tab": True,
            "conditions": [{"condition_type": "print_job", "printing": True}],
            "output": rpi_output.get("index_id"),
            "toggle_timer_on": rpi_output.get("toggle_timer_on", 0),
            "toggle_timer_off": rpi_output.get("toggle_timer_off", 0),
        }
        if rpi_output.get("output_type") == "pwm":
            automation["duty_cycle"] = _to_float(rpi_output.get("default_duty_cycle"))
        automations.append(automation)


def _replace_thermostat_no_maximum_temperature_with_null(rpi_outputs: list[dict]) -> None:
    """Replace the `temp_ctr_max_temp` of a thermostat that has no maximum temperature with null.

    A thermostat with no maximum temperature used to save 0 or less, or nothing.
    Version 11 saves null, so that 0 is a temperature like the others.
    """
    for rpi_output in rpi_outputs:
        if _to_float(rpi_output.get("temp_ctr_max_temp")) <= 0:
            rpi_output["temp_ctr_max_temp"] = None


def _convert_temperatures_to_celsius(
    rpi_inputs: list[dict],
    rpi_outputs: list[dict],
    automations: list[dict],
    settings: PluginSettings,
) -> None:
    """Replace the per-sensor `use_fahrenheit` with one `temperature_unit` global setting.

    Each entered temperature used to be saved in the unit of its sensor.
    Version 11 saves and computes in Celsius and converts for display only.
    """
    # Get which sensors use which units of measurement
    fahrenheit_sensor_ids = set()
    celsius_sensor_ids = set()
    for rpi_input in rpi_inputs:
        use_fahrenheit = bool(rpi_input.pop("use_fahrenheit", False))
        if rpi_input.get("input_type") != "temperature_sensor":
            continue
        if use_fahrenheit:
            fahrenheit_sensor_ids.add(_to_int(rpi_input.get("index_id")))
        else:
            celsius_sensor_ids.add(_to_int(rpi_input.get("index_id")))

    # Set the new global temperature unit, based on which one the sensors utilize the most
    new_unit_should_be_fahrenheit = len(fahrenheit_sensor_ids) > len(celsius_sensor_ids)
    settings.set(
        ["temperature_unit"],
        (TemperatureUnit.FAHRENHEIT if new_unit_should_be_fahrenheit else TemperatureUnit.CELSIUS).value,
    )

    # Convert all saved temperatures to Celsius
    fahrenheit = TemperatureUnit.FAHRENHEIT
    for rpi_output in rpi_outputs:
        is_temperature_thermostat = (
            rpi_output.get("output_type") == "temp_hum_control" and rpi_output.get("temp_ctr_type") != "dehumidifier"
        )
        if not is_temperature_thermostat or _to_int(rpi_output.get("linked_temp_sensor")) not in fahrenheit_sensor_ids:
            continue
        if _to_float(rpi_output.get("temp_ctr_default_value")) != 0:
            rpi_output["temp_ctr_default_value"] = fahrenheit.to_celsius(
                _to_float(rpi_output.get("temp_ctr_default_value")),
            )
        rpi_output["temp_ctr_deadband"] = fahrenheit.to_celsius_interval(
            _to_float(rpi_output.get("temp_ctr_deadband")),
        )
        if rpi_output.get("temp_ctr_max_temp") is not None:
            rpi_output["temp_ctr_max_temp"] = fahrenheit.to_celsius(_to_float(rpi_output.get("temp_ctr_max_temp")))
    for automation in automations:
        if _to_int(automation.get("linked_temp_sensor")) not in fahrenheit_sensor_ids:
            continue
        if automation.get("automation_type") == "pwm_temperature_linked":
            for key in ("temperature_a", "temperature_b"):
                automation[key] = fahrenheit.to_celsius(_to_float(automation.get(key)))
        elif automation.get("trigger_type") == "temperature" and _to_float(automation.get("alarm_set_temp")) != 0:
            automation["alarm_set_temp"] = fahrenheit.to_celsius(_to_float(automation.get("alarm_set_temp")))


def _convert_auto_startup_shutdown_to_automations(rpi_outputs: list[dict], automations: list[dict]) -> None:
    """Turn the automatic on/off fields of each output into automation rules on OctoPrint events.

    Outputs used to carry `auto_startup` and `startup_time` (on at print start, after N seconds or at HH:MM),
    `auto_shutdown` and `shutdown_time` (off at print end, the same way), `shutdown_on_failed`, `shutdown_on_error`
    and `startup_with_server`, plus the value to turn on with: a PWM duty, a LED color or a thermostat target. Each
    becomes an automation rule with an "octoprint_event" trigger and an "output_control" reaction, so that an output
    holds only its hardware:

    - every output gets a print start and a print end rule, enabled as the old flags were;
      a delay or a time of day adds a "print_job" condition, so that the rule cannot fire outside the print;
    - `shutdown_on_failed` adds the cancel and failure events to the print end rule; a thermostat with a delayed end
      rule gets a separate, immediate "on print failure" rule, so that a heater never stays on after a failure;
    - `shutdown_on_error` and `startup_with_server` become rules only when on;
    - a PWM with a curve also gets "Turn on ... at print end" with its default duty, because in version 10 it went
      back to the default when the print ended.
    """

    def add_rule(
        rpi_output,
        events,
        state,
        *,
        enabled,
        show_in_tab=False,
        time=0,
        printing=None,
        setpoint=None,
    ) -> None:
        # Delay or time of day: startup_time and shutdown_time held seconds, or HH:MM
        time_of_day = parse_hhmm(str(time))
        delay = 0 if time_of_day is not None else max(_to_float(time), 0)
        at = time_of_day.strftime("%H:%M") if time_of_day is not None else ""

        # Condition on the print job, only for a delayed rule
        conditions = []
        if printing is not None and (delay > 0 or at):
            conditions.append({"condition_type": "print_job", "printing": printing})

        # Label suffixes of the automation rule
        label_suffixes = {
            ("PrintStarted",): "at print start",
            ("PrintDone",): "at print end",
            ("PrintDone", "PrintCancelled", "PrintFailed"): "at print end",
            ("PrintCancelled", "PrintFailed"): "on print failure",
            ("Error", "Disconnected"): "on printer error",
            ("Startup",): "at server start",
        }

        # Append the automation rule
        automations.append(
            {
                "index_id": _new_id(automations),
                "label": f"Turn {state} {rpi_output.get('label')} {label_suffixes.get(tuple(events), '')}".strip(),
                "automation_type": "rule",
                "enabled": enabled,
                "show_in_tab": show_in_tab,
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

    # Get ids of the PWM outputs linked to a PWM temperature automation
    pwm_temperature_linked_ids = {
        _to_int(automation.get("output"))
        for automation in automations
        if automation.get("automation_type") == "pwm_temperature_linked"
    }

    for rpi_output in rpi_outputs:
        # Get output fields
        output_type = rpi_output.get("output_type")
        auto_startup = bool(rpi_output.get("auto_startup"))
        startup_time = rpi_output.get("startup_time", 0)
        auto_shutdown = bool(rpi_output.get("auto_shutdown"))
        shutdown_time = rpi_output.get("shutdown_time", 0)
        shutdown_on_failed = bool(rpi_output.get("shutdown_on_failed"))
        shutdown_on_error = bool(rpi_output.get("shutdown_on_error"))
        startup_with_server = bool(rpi_output.get("startup_with_server"))
        has_toggle_timer = output_type in ("regular", "pwm") and bool(rpi_output.get("toggle_timer"))
        default_duty_cycle = _to_float(rpi_output.get("default_duty_cycle")) if output_type == "pwm" else 0

        # Prepare setpoint to turn on with, from the defaults of the output
        on_setpoint: dict | None = {}
        if output_type == "pwm":
            on_setpoint = {"duty_cycle": default_duty_cycle} if default_duty_cycle > 0 else None
        elif output_type in ("ledstrip", "neopixel_direct", "neopixel_indirect"):
            color_key = "default_ledstrip_color" if output_type == "ledstrip" else "default_neopixel_color"
            color = str(rpi_output.get(color_key, ""))

            # Convert color to the hex format, black if it was invalid
            match = re.fullmatch(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", color)
            rgb = Rgb(*(int(part) for part in match.groups())) if match else Rgb(0, 0, 0)
            is_color = rgb != Rgb(0, 0, 0) and max(rgb) <= 255
            on_setpoint = {"color": format_hex_color(rgb)} if is_color else None
        elif output_type == "temp_hum_control":
            target = _to_float(rpi_output.get("temp_ctr_default_value"))
            on_setpoint = {"target": target} if target != 0 else None
        is_pwm_temperature_linked = _to_int(rpi_output.get("index_id")) in pwm_temperature_linked_ids
        if is_pwm_temperature_linked:
            on_setpoint = None

        # Where the tab showed the Auto Startup and Auto Shutdown toggles
        toggles_were_shown = not is_pwm_temperature_linked and not has_toggle_timer

        # Create print start rule
        if on_setpoint is not None:
            add_rule(
                rpi_output,
                ["PrintStarted"],
                "on",
                enabled=auto_startup,
                show_in_tab=toggles_were_shown,
                time=startup_time,
                printing=True,
                setpoint=on_setpoint,
            )

        # Create print end rule of a PWM driven by a curve, back to its default duty
        if is_pwm_temperature_linked and default_duty_cycle > 0:
            add_rule(
                rpi_output,
                ["PrintDone", "PrintCancelled", "PrintFailed"],
                "on",
                enabled=True,
                setpoint={"duty_cycle": default_duty_cycle},
            )

        # Create print end rule
        shutdown_is_delayed = parse_hhmm(str(shutdown_time)) is not None or _to_float(shutdown_time) > 0
        failure_has_own_rule = output_type == "temp_hum_control" and shutdown_is_delayed
        end_events = ["PrintDone"]
        if shutdown_on_failed and not failure_has_own_rule:
            end_events += ["PrintCancelled", "PrintFailed"]
        add_rule(
            rpi_output,
            end_events,
            "off",
            enabled=auto_shutdown,
            show_in_tab=toggles_were_shown,
            time=shutdown_time,
            printing=False,
        )

        # Create print failure rule of a thermostat with a delayed print end rule
        if shutdown_on_failed and failure_has_own_rule:
            add_rule(
                rpi_output,
                ["PrintCancelled", "PrintFailed"],
                "off",
                enabled=auto_shutdown,
                show_in_tab=toggles_were_shown,
            )

        # Create printer error rule
        if shutdown_on_error:
            add_rule(rpi_output, ["Error", "Disconnected"], "off", enabled=True)

        # Create server start rule
        if startup_with_server and on_setpoint is not None:
            add_rule(rpi_output, ["Startup"], "on", enabled=True, setpoint=on_setpoint)


def _remove_keys_of_other_item_kinds(rpi_outputs: list[dict], actions: list[dict], automations: list[dict]) -> None:
    """Remove from each settings item the keys of the other kinds of item.

    Version 10 gave every output every key, because the settings page needed them all. From version 11 an output holds
    only its hardware: it drops the keys of the actions, alarms, curves, toggle timers and automatic fields, which now
    live in `actions` and `automations`, and the actions and the automations keep only the keys of their own kind.
    """
    output_keys_to_remove = (
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
        "toggle_timer",
        "toggle_timer_on",
        "toggle_timer_off",
        "default_duty_cycle",
        "default_ledstrip_color",
        "default_neopixel_color",
        "temp_ctr_default_value",
    )
    for rpi_output in rpi_outputs:
        for key in output_keys_to_remove:
            rpi_output.pop(key, None)

    action_keys_to_keep = {
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
        for key in set(action) - action_keys_to_keep:
            del action[key]

    automation_keys_to_keep = {
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
        "show_in_tab",
        "action",
        "output",
        "temperature_a",
        "duty_a",
        "temperature_b",
        "duty_b",
        "toggle_timer_on",
        "toggle_timer_off",
        "duty_cycle",
        "color",
        "target",
    }
    for automation in automations:
        for key in set(automation) - automation_keys_to_keep:
            del automation[key]


def _replace_empty_numbers_with_zero(rpi_outputs: list[dict], automations: list[dict]) -> None:
    """Replace the numbers saved empty with 0.

    Version 10 read an empty or missing number as 0. Version 11 reads numbers strictly and would reject the item, so
    the fields that could be left blank must be set to 0.
    """
    number_keys_by_item_type = {
        "temp_hum_control": ("temp_ctr_deadband",),
        "pwm_temperature_linked": ("temperature_a", "duty_a", "temperature_b", "duty_b"),
        "toggle_timer": ("toggle_timer_on", "toggle_timer_off"),
    }
    for item_settings in [*rpi_outputs, *automations]:
        item_type = item_settings.get("output_type") or item_settings.get("automation_type") or ""
        for key in number_keys_by_item_type.get(item_type, ()):
            if item_settings.get(key) in ("", None):
                item_settings[key] = 0


def _add_keys_of_every_type_with_defaults(actions: list[dict], automations: list[dict]) -> None:
    """Add to each action the keys of every action type, and to each automation those of every automation type.

    The settings page binds every key of every type when it loads, so changing the type of an item needs all of
    them present.
    """
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
        "show_in_tab": False,
        "action": "",
        "output": "",
        "temperature_a": 0,
        "duty_a": 0,
        "temperature_b": 0,
        "duty_b": 0,
        "toggle_timer_on": 0,
        "toggle_timer_off": 0,
        "duty_cycle": 0,
        "color": "",
        "target": None,
    }
    reaction_defaults = {
        "reaction_type": "output_control",
        "controlled_io": "",
        "controlled_io_set_state": "on",
        "duty_cycle": 0,
        "color": "",
        "target": None,
        "action": "",
    }
    for automation in automations:
        for key, value in automation_defaults.items():
            automation.setdefault(key, value)
        automation.setdefault("reactions", [{}])
        for reaction in automation["reactions"]:
            for key, value in reaction_defaults.items():
                reaction.setdefault(key, value)


def _move_neopixel_dma_to_each_output(rpi_outputs: list[dict], settings: PluginSettings) -> None:
    """Move the NeoPixel DMA channel from the global `neopixel_dma` to each output.

    One channel used to serve every NeoPixel driven by the Raspberry Pi. Now each output has its own `neopixel_dma`, so
    that two outputs can use different channels: it gets the old global value, or 10 (the default) if it was never
    set, and the global key is removed.
    """
    neopixel_dma = settings.get_int(["neopixel_dma"])
    for rpi_output in rpi_outputs:
        rpi_output["neopixel_dma"] = 10 if neopixel_dma is None else neopixel_dma
    settings.remove(["neopixel_dma"])


def _remove_use_sudo(settings: PluginSettings) -> None:
    """Remove the global `use_sudo` setting.

    The user used to choose whether the sensor and NeoPixel scripts ran with sudo. The plugin now decides by itself
    what needs root, so the key goes.
    """
    settings.remove(["use_sudo"])


def _convert_board_pins_to_bcm(rpi_inputs: list[dict], rpi_outputs: list[dict], settings: PluginSettings) -> None:
    """Convert every GPIO physical pin number to BCM and remove the global `use_board_pin_number` setting.

    Pins could be numbered by their position on the header (BOARD). Version 11 uses BCM only.
    The pins of the GPIO inputs and of the outputs on a pin are converted; a BOARD position that
    is not a GPIO (power or ground) becomes empty.
    """
    if settings.get_boolean(["use_board_pin_number"]):
        # The pin_to_gpio_rev3 table of RPi.GPIO (source/common.c)
        board_to_bcm = {
            3: 2, 5: 3, 7: 4, 8: 14, 10: 15, 11: 17, 12: 18, 13: 27, 15: 22, 16: 23, 18: 24, 19: 10, 21: 9,
            22: 25, 23: 11, 24: 8, 26: 7, 29: 5, 31: 6, 32: 12, 33: 13, 35: 19, 36: 16, 37: 26, 38: 20, 40: 21,
        }  # fmt: skip

        for rpi_input in rpi_inputs:
            pin = _to_int(rpi_input.get("gpio_pin"))
            if rpi_input.get("input_type") == "gpio" and pin > 0:
                rpi_input["gpio_pin"] = board_to_bcm.get(pin, "")

        for rpi_output in rpi_outputs:
            output_type = rpi_output.get("output_type")
            is_switch = output_type in ("regular", "temp_hum_control")
            uses_pin = output_type == "pwm" or (is_switch and not rpi_output.get("gpio_i2c_enabled"))
            pin = _to_int(rpi_output.get("gpio_pin"))
            if uses_pin and pin > 0:
                rpi_output["gpio_pin"] = board_to_bcm.get(pin, "")

    settings.remove(["use_board_pin_number"])
