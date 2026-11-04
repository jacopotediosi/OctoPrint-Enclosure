from __future__ import annotations

import contextlib
import copy
import functools
from typing import TYPE_CHECKING

import octoprint.plugin
from flask import jsonify, make_response, request
from werkzeug.exceptions import BadRequest

from octoprint_enclosure.actions import Action, ActionError, GcodeAction, PrinterAction, ShellAction
from octoprint_enclosure.core import MeasurementType, TemperatureUnit
from octoprint_enclosure.inputs import PullResistor, Reading
from octoprint_enclosure.outputs import (
    ColorSetpoint,
    LedstripOutput,
    NeopixelDirectOutput,
    NeopixelIndirectOutput,
    OutputError,
    PwmOutput,
    PwmSetpoint,
    RegularOutput,
    RegularSetpoint,
    ThermostatOutput,
)
from octoprint_enclosure.utils import Rgb, is_number, is_rgb, parse_float, parse_rgb, to_float, to_int

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from flask import Response

    from octoprint_enclosure.actions import Actions
    from octoprint_enclosure.control_loop import ControlLoop
    from octoprint_enclosure.core import PluginContext, Settings
    from octoprint_enclosure.hardware import GpioBackend
    from octoprint_enclosure.inputs import SensorPoller
    from octoprint_enclosure.output_executor import OutputExecutor
    from octoprint_enclosure.outputs import Output, Outputs
    from octoprint_enclosure.outputs.color import ColorOutput


_JSON_TYPES: dict[str, Callable[[object], bool]] = {
    "bool": lambda value: isinstance(value, bool),
    "number": is_number,
    "percent": lambda value: is_number(value) and 0 <= value <= 100,
    "byte": lambda value: is_number(value) and 0 <= value <= 255,
    "str": lambda value: isinstance(value, str),
    "rgb": lambda value: isinstance(value, str) and is_rgb(value),
}

_STATE_LABELS = {True: "ON", False: "OFF"}


def _expects_json(**fields: str) -> Callable[[Callable[..., Response]], Callable[..., Response]]:
    """Check if the JSON body of the request is valid and passes its fields to a route, as keyword arguments.

    Args:
        **fields (str): The fields the body must have, with the type of their JSON value.

    Returns:
        Callable[[Callable[..., Response]], Callable[..., Response]]: The decorator of the route.

    """

    def decorator(route: Callable[..., Response]) -> Callable[..., Response]:
        @functools.wraps(route)
        def wrapper(*args: object, **kwargs: object) -> Response:
            if not request.is_json:
                return make_response("Content-Type is not json", 415)

            try:
                data = request.get_json()
            except BadRequest:
                return make_response("Malformed request", 400)
            if not isinstance(data, dict):
                return make_response("Body is not a json object", 422)

            missing = [name for name in fields if name not in data]
            invalid = [name for name in fields if name in data and not _JSON_TYPES[fields[name]](data[name])]
            errors = []
            if missing:
                errors.append("Missing attributes: " + ", ".join(f"'{name}'" for name in missing) + ".")
            if invalid:
                errors.append(
                    "Invalid attributes: " + ", ".join(f"'{name}' is not {fields[name]}" for name in invalid) + ".",
                )
            if errors:
                return make_response(" ".join(errors), 422)

            return route(*args, **kwargs, **{name: data[name] for name in fields})

        return wrapper

    return decorator


class Api(octoprint.plugin.BlueprintPlugin):
    """The plugin HTTP APIs."""

    _identifier: str
    _basefolder: str
    _settings: Settings
    _gpio: GpioBackend
    _outputs: Outputs
    _actions: Actions
    _output_executor: OutputExecutor
    _control_loop: ControlLoop
    _sensor_poller: SensorPoller
    _logger: logging.Logger

    _update_ui: Callable[[], None]
    """The function refreshing the UI."""

    _set_auto_startup_enabled: Callable[[int, bool], None]
    """The function enabling or disabling the auto startup of an output, with the id of the output and whether to
    enable it."""

    _set_auto_shutdown_enabled: Callable[[int, bool], None]
    """The function enabling or disabling the auto shutdown of an output, with the id of the output and whether to
    enable it."""

    _set_filament_sensor_enabled: Callable[[int, bool], None]
    """The function enabling or disabling the filament sensors of a GPIO input, with the id of the input and whether
    to enable them."""

    def __init__(
        self,
        plugin_context: PluginContext,
        *,
        update_ui: Callable[[], None],
        set_auto_startup_enabled: Callable[[int, bool], None],
        set_auto_shutdown_enabled: Callable[[int, bool], None],
        set_filament_sensor_enabled: Callable[[int, bool], None],
    ) -> None:
        """Set up the API.

        Args:
            plugin_context (PluginContext): The plugin context.
            update_ui (Callable[[], None]): The function refreshing the UI.
            set_auto_startup_enabled (Callable[[int, bool], None]): The function enabling or disabling the auto
                startup of an output, with the id of the output and whether to enable it.
            set_auto_shutdown_enabled (Callable[[int, bool], None]): The function enabling or disabling the auto
                shutdown of an output, with the id of the output and whether to enable it.
            set_filament_sensor_enabled (Callable[[int, bool], None]): The function enabling or disabling the
                filament sensors of a GPIO input, with the id of the input and whether to enable them.

        """
        self._identifier = plugin_context.identifier
        self._basefolder = plugin_context.basefolder
        self._settings = plugin_context.settings
        self._gpio = plugin_context.gpio
        self._outputs = plugin_context.outputs
        self._actions = plugin_context.actions
        self._output_executor = plugin_context.output_executor
        self._control_loop = plugin_context.control_loop
        self._sensor_poller = plugin_context.sensor_poller
        self._logger = plugin_context.logger.getChild("Api")

        self._update_ui = update_ui
        self._set_auto_startup_enabled = set_auto_startup_enabled
        self._set_auto_shutdown_enabled = set_auto_shutdown_enabled
        self._set_filament_sensor_enabled = set_filament_sensor_enabled

    ##########
    ### Routes
    ##########

    @octoprint.plugin.BlueprintPlugin.route("/inputs", methods=["GET"])
    def get_inputs(self) -> Response:
        inputs = []
        for input_settings in self._settings.rpi_inputs:
            payload = {
                "index_id": to_int(input_settings["index_id"]),
                "label": input_settings["label"],
                "GPIO_Pin": None,
                "State": None,
            }
            if input_settings["input_type"] == "gpio":
                pin = to_int(input_settings["gpio_pin"])
                active_low = input_settings["input_pull_resistor"] == PullResistor.UP.value
                payload["GPIO_Pin"] = pin
                payload["State"] = self._pin_state_human(pin, active_low=active_low)
            inputs.append(payload)
        return jsonify(inputs)

    @octoprint.plugin.BlueprintPlugin.route("/inputs/<int:input_id>", methods=["GET"])
    def get_input(self, input_id: int) -> Response:
        input_settings = self._get_input_settings(input_id)

        if input_settings is None:
            return make_response("", 404)

        payload = copy.deepcopy(input_settings)
        try:
            reading = self._sensor_poller.get_reading(input_id)
        except LookupError:
            reading = Reading()
        temperature_unit = self._settings.temperature_unit
        payload["use_fahrenheit"] = temperature_unit is TemperatureUnit.FAHRENHEIT
        payload["temp_sensor_temp"] = (
            "" if reading.temperature is None else temperature_unit.from_celsius(reading.temperature)
        )
        payload["temp_sensor_humidity"] = "" if reading.humidity is None else reading.humidity
        return jsonify(payload)

    @octoprint.plugin.BlueprintPlugin.route("/temperature/<int:output_id>", methods=["PATCH"])
    @_expects_json(temperature="number")
    def set_thermostat_target(self, output_id: int, *, temperature: float) -> Response:
        try:
            thermostat_output = self._outputs.get(output_id, ThermostatOutput)
        except OutputError:
            return make_response("", 204)
        # 0 turns the thermostat off, in every unit
        target = float(temperature)
        if target != 0 and thermostat_output.config.temp_ctr_type.measurement_type is MeasurementType.TEMPERATURE:
            target = self._settings.temperature_unit.to_celsius(target)
        self._control_loop.set_thermostat_target(output_id, target)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/filament/<int:input_id>", methods=["PATCH"])
    @_expects_json(status="bool")
    def set_filament_sensor(self, input_id: int, *, status: bool) -> Response:
        self._set_filament_sensor_enabled(input_id, status)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/outputs", methods=["GET"])
    def get_outputs(self) -> Response:
        outputs = []
        for output_settings in self._settings.rpi_outputs:
            if output_settings["output_type"] == "regular":
                output_id = to_int(output_settings["index_id"])
                outputs.append(
                    {
                        "index_id": output_id,
                        "label": output_settings["label"],
                        "GPIO_Pin": to_int(output_settings["gpio_pin"]),
                        "State": self._output_state_human(output_id, RegularOutput),
                    },
                )
        return jsonify(outputs)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:output_id>", methods=["GET"])
    def get_output(self, output_id: int) -> Response:
        output_settings = self._get_output_settings(output_id)

        if output_settings is None:
            return make_response("", 404)

        payload = copy.deepcopy(output_settings)
        payload["gpio_status"] = False
        payload["current_value"] = False
        payload["duty_cycle"] = 0
        payload["neopixel_color"] = "rgb(0,0,0)"
        payload["ledstrip_color"] = "rgb(0,0,0)"
        payload["temp_ctr_set_value"] = 0

        # The settings hold the temperatures in Celsius, the API gives them in the temperature unit of the settings
        output_type = payload["output_type"]
        temperature_unit = self._settings.temperature_unit
        if output_type == "temp_hum_control" and payload["temp_ctr_type"] != "dehumidifier":
            # 0 is the thermostat off, and 0 or less is no maximum, in every unit
            if to_float(payload["temp_ctr_default_value"]) != 0:
                payload["temp_ctr_default_value"] = self._converted(
                    payload["temp_ctr_default_value"],
                    temperature_unit.from_celsius,
                )
            if to_float(payload["temp_ctr_max_temp"]) > 0:
                payload["temp_ctr_max_temp"] = self._converted(
                    payload["temp_ctr_max_temp"],
                    temperature_unit.from_celsius,
                )
            payload["temp_ctr_deadband"] = self._converted(
                payload["temp_ctr_deadband"],
                temperature_unit.from_celsius_interval,
            )

        if output_type == "regular":
            payload["current_value"] = self._output_state_boolean(output_id, RegularOutput)
            payload["gpio_status"] = payload["current_value"] is True
        elif output_type == "temp_hum_control":
            payload["current_value"] = self._output_state_boolean(output_id, ThermostatOutput)
            payload["gpio_status"] = payload["current_value"] is True
            thermostat = self._control_loop.get_thermostats().get(output_id)
            if thermostat is not None:
                # 0 is the thermostat off, in every unit
                temperature_unit = self._settings.temperature_unit
                target = thermostat.target
                is_temperature = thermostat.config.temp_ctr_type.measurement_type is MeasurementType.TEMPERATURE
                if target != 0 and is_temperature:
                    target = temperature_unit.from_celsius(target)
                payload["temp_ctr_set_value"] = target
        elif output_type == "pwm":
            with contextlib.suppress(OutputError):
                payload["duty_cycle"] = self._outputs.get(output_id, PwmOutput).duty_cycle
            payload["current_value"] = payload["duty_cycle"] > 0
        elif output_type in ("neopixel_indirect", "neopixel_direct"):
            neopixel_class = NeopixelDirectOutput if output_type == "neopixel_direct" else NeopixelIndirectOutput
            payload["neopixel_color"] = self._output_color(output_id, neopixel_class)
            payload["current_value"] = payload["neopixel_color"] != "rgb(0,0,0)"
        elif output_type == "ledstrip":
            payload["ledstrip_color"] = self._output_color(output_id, LedstripOutput)
            payload["current_value"] = payload["ledstrip_color"] != "rgb(0,0,0)"
        return jsonify(payload)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:output_id>", methods=["PATCH"])
    @_expects_json(status="bool")
    def set_output(self, output_id: int, *, status: bool) -> Response:
        try:
            self._outputs.get(output_id, RegularOutput)
        except OutputError as error:
            self._logger.debug("Can't switch output %s: %s", output_id, error)
            return make_response("", 204)
        if status:
            self._output_executor.turn_on(output_id, RegularSetpoint(), wait=True)
        else:
            self._output_executor.turn_off(output_id, wait=True)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:output_id>/auto-startup", methods=["PATCH"])
    @_expects_json(status="bool")
    def set_auto_startup(self, output_id: int, *, status: bool) -> Response:
        self._set_auto_startup_enabled(output_id, status)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:output_id>/auto-shutdown", methods=["PATCH"])
    @_expects_json(status="bool")
    def set_auto_shutdown(self, output_id: int, *, status: bool) -> Response:
        self._set_auto_shutdown_enabled(output_id, status)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/pwm/<int:output_id>", methods=["PATCH"])
    @_expects_json(duty_cycle="percent")
    def set_pwm(self, output_id: int, *, duty_cycle: float) -> Response:
        if self._get_output_settings(output_id) is not None:
            self._output_executor.turn_on(output_id, PwmSetpoint(int(duty_cycle)), wait=True)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/rgb-led/<int:output_id>", methods=["PATCH"])
    @_expects_json(rgb="rgb")
    def set_ledstrip_color(self, output_id: int, *, rgb: str) -> Response:
        red, green, blue = parse_rgb(rgb)
        if self._get_output_settings(output_id) is not None:
            setpoint = ColorSetpoint(Rgb(to_int(red), to_int(green), to_int(blue)))
            self._output_executor.turn_on(output_id, setpoint, wait=True)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/neopixel/<int:output_id>", methods=["PATCH"])
    @_expects_json(red="byte", green="byte", blue="byte")
    def set_neopixel_color(self, output_id: int, *, red: float, green: float, blue: float) -> Response:
        if self._get_output_settings(output_id) is not None:
            setpoint = ColorSetpoint(Rgb(int(red), int(green), int(blue)))
            self._output_executor.turn_on(output_id, setpoint, wait=True)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/update", methods=["POST"])
    def update_ui(self) -> Response:
        self._update_ui()
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/shell/<int:action_id>", methods=["POST"])
    def run_shell_action(self, action_id: int) -> Response:
        return self._run_action(action_id, ShellAction)

    @octoprint.plugin.BlueprintPlugin.route("/gcode/<int:action_id>", methods=["POST"])
    def run_gcode_action(self, action_id: int) -> Response:
        return self._run_action(action_id, GcodeAction)

    @octoprint.plugin.BlueprintPlugin.route("/printer/<int:action_id>", methods=["POST"])
    def run_printer_action(self, action_id: int) -> Response:
        return self._run_action(action_id, PrinterAction)

    ##########
    ### Helpers
    ##########

    def _converted(self, value: object, convert: Callable[[float], float]) -> object:
        # A value that isn't a number is returned as it is
        try:
            number = parse_float(value)
        except (TypeError, ValueError, OverflowError):
            return value
        return convert(number)

    def _run_action(self, action_id: int, action_class: type[Action]) -> Response:
        try:
            self._actions.run(action_id, action_class)
        except ActionError as error:
            self._logger.debug("Can't run action %s: %s", action_id, error)
        return make_response("", 204)

    def _get_input_settings(self, input_id: int) -> dict | None:
        return next((item for item in self._settings.rpi_inputs if to_int(item["index_id"]) == input_id), None)

    def _get_output_settings(self, output_id: int) -> dict | None:
        return next((item for item in self._settings.rpi_outputs if to_int(item["index_id"]) == output_id), None)

    def _pin_state_human(self, pin: int, *, active_low: bool) -> str:
        try:
            state = self._gpio.input(pin)
        except Exception:
            self._logger.exception("Error reading pin %s", pin)
            return "ERROR: Unable to read pin"
        return _STATE_LABELS[(not state) if active_low else bool(state)]

    def _output_state_boolean(self, output_id: int, output_class: type[Output]) -> bool | str:
        try:
            return self._outputs.get(output_id, output_class).is_on()
        except OutputError:
            return "ERROR: Unable to read pin"
        except Exception:
            self._logger.exception("Error reading output %s", output_id)
            return "ERROR: Unable to read pin"

    def _output_state_human(self, output_id: int, output_class: type[Output]) -> str:
        state = self._output_state_boolean(output_id, output_class)
        return state if isinstance(state, str) else _STATE_LABELS[state]

    def _output_color(self, output_id: int, output_class: type[ColorOutput]) -> str:
        try:
            color = self._outputs.get(output_id, output_class).color
        except OutputError:
            color = None

        red, green, blue = (0, 0, 0) if color is None else color

        return f"rgb({red},{green},{blue})"
