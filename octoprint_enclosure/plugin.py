import contextlib
import copy
import logging
import sys
import threading
from datetime import timedelta
from pathlib import Path

import octoprint.plugin
import octoprint.util
import smbus2
from flask import jsonify, make_response, request
from octoprint.events import Events
from octoprint.logging.handlers import CleaningTimedRotatingFileHandler
from octoprint.server.util.flask import restricted_access
from octoprint.util import RepeatedTimer
from werkzeug.exceptions import BadRequest

from .actions import ActionError, Actions, GcodeAction, GcodeConfig, PrinterAction, ShellAction
from .automations import (
    AutomationError,
    Automations,
    FilamentAutomation,
    GpioInputTrigger,
    OutputControlReaction,
    PwmTemperatureLinkedAutomation,
    RuleAutomation,
    RunActionReaction,
    StopTempHumControlReaction,
    TemperatureTrigger,
)
from .core import Frontend, Settings
from .core.migrations import migrate_settings
from .gcode_commands import EncDevHandler, EncHandler
from .hardware import dummy_gpio, dummy_i2c, gpio
from .inputs import GpioInputError, GpioInputs, PullResistor, SensorError, Sensors
from .integrations import Mqtt
from .notifications import Notifications, NotificationType
from .outputs import (
    LedstripOutput,
    NeopixelDirectOutput,
    NeopixelIndirectOutput,
    OutputError,
    Outputs,
    PwmOutput,
    RegularOutput,
    RegularSetState,
    TempHumControlOutput,
    TempHumControlStatus,
    TempHumControlType,
)
from .utils import (
    is_hhmm,
    parse_rgb,
    seconds_until_next,
    seconds_until_today_at,
    to_float,
    to_int,
)


class EnclosurePlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.BlueprintPlugin,
    octoprint.plugin.EventHandlerPlugin,
):
    rpi_outputs = []
    rpi_inputs = []
    actions = []
    automations = []
    waiting_temperature = set()
    rpi_outputs_not_changed = []
    event_queue = []
    temperature_sensor_data = []
    failing_sensors = set()
    sensors_lock = threading.Lock()
    print_complete = False
    development_mode = False

    def initialize(self):
        # Logging formatter
        logging_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        # File logging handler
        file_handler = CleaningTimedRotatingFileHandler(
            self._settings.get_plugin_logfile_path(),
            when="D",
            backupCount=6,
        )
        file_handler.setFormatter(logging_formatter)
        self._logger.addHandler(file_handler)

        # Console logging handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging_formatter)
        self._logger.addHandler(console_handler)

        # Don't propagate logging
        self._logger.propagate = False

        # Initialize other plugin components
        self._enclosure_settings = Settings(self._settings)
        self._frontend = Frontend(self._plugin_manager, self._identifier)
        self._notifications = Notifications(self._enclosure_settings, self._logger)
        self._mqtt = Mqtt(self._plugin_manager, self._logger)

        # Init GPIO
        self.development_mode = self._enclosure_settings.development_mode
        if self.development_mode:
            self._gpio = dummy_gpio
            self._i2c = dummy_i2c
            self._logger.warning("Development mode is enabled: GPIO and I2C (pins, sensors, etc) are simulated")
        else:
            self._gpio = gpio
            self._i2c = smbus2

        # Init G-code command handlers
        self._enc_handler = EncHandler(self)
        self._encdev_handler = EncDevHandler(self)

    def start_timer(self):
        """Start the timer that checks the enclosure temperature."""
        self._check_temp_timer = RepeatedTimer(10, self.check_enclosure_temp, None, None, True)
        self._check_temp_timer.start()

    def pin_state_boolean(self, pin, active_low):
        try:
            state = self._gpio.input(pin)
            return (not state) if active_low else bool(state)
        except Exception:
            return "ERROR: Unable to read pin"

    def pin_state_human(self, pin, active_low):
        pin_state = self.pin_state_boolean(pin, active_low)
        if pin_state is True:
            return " ON "
        if pin_state is False:
            return " OFF "
        return pin_state

    def output_state_boolean(self, index_id, output_class):
        try:
            return self._outputs.get(index_id, output_class).is_on()
        except OutputError:
            return "ERROR: Unable to read pin"
        except Exception:
            self._logger.exception("Error reading output %s", index_id)
            return "ERROR: Unable to read pin"

    def output_state_human(self, index_id, output_class):
        output_state = self.output_state_boolean(index_id, output_class)
        if output_state is True:
            return " ON "
        if output_state is False:
            return " OFF "
        return output_state

    # ~~ StartupPlugin mixin
    def on_after_startup(self):
        self._mqtt.load_helpers()

        self.event_queue = []
        self.rpi_outputs_not_changed = []
        self.rpi_outputs = self._enclosure_settings.rpi_outputs
        self.rpi_inputs = self._enclosure_settings.rpi_inputs
        self.actions = self._enclosure_settings.actions
        self.automations = self._enclosure_settings.automations
        # Reset volatile temp_ctr_set_value to 0 on startup (it should not be persisted)
        for rpi_output in self.rpi_outputs:
            rpi_output["temp_ctr_set_value"] = 0
        self.configure_outputs()
        self.configure_gpio_inputs()
        self.configure_actions()
        self.configure_automations()
        self.setup_gpio()
        self.configure_gpio()
        self.configure_sensors()
        self.update_ui()
        self.start_outpus_with_server()
        self.handle_initial_gpio_control()
        self.start_timer()
        self.print_complete = False

    def get_settings_version(self):
        return 11

    def on_settings_migrate(self, target, current=None):
        migrate_settings(target, current, self._settings, self._logger)

    # ~~ Blueprintplugin mixin
    def is_blueprint_csrf_protected(self):
        return True

    @octoprint.plugin.BlueprintPlugin.route("/ReadPin/<int:identifier>", methods=["GET"])
    def read_single_pin(self, identifier):
        resp = []
        match_found = False
        for rpi_input in self.rpi_inputs:
            if identifier == to_int(rpi_input["gpio_pin"]):
                match_found = True
                configured_as = "Input"
                active_low = rpi_input["input_pull_resistor"] == PullResistor.UP.value
                pin = to_int(rpi_input["gpio_pin"])
                val = self.pin_state_human(pin, active_low)
                label = rpi_input["label"]
                resp.append(
                    {
                        "Configured_As": configured_as,
                        "label": label,
                        "GPIO_Pin": pin,
                        "Active_Low": active_low,
                        "State": val,
                    },
                )
        for rpi_output in self.rpi_outputs:
            if identifier == to_int(rpi_output["gpio_pin"]):
                match_found = True
                configured_as = "Output"
                pin = to_int(rpi_output["gpio_pin"])
                if rpi_output["output_type"] in ("regular", "temp_hum_control"):
                    active_low = bool(rpi_output["active_low"])
                    output_class = RegularOutput if rpi_output["output_type"] == "regular" else TempHumControlOutput
                    val = self.output_state_human(to_int(rpi_output["index_id"]), output_class)
                else:
                    active_low = False
                    val = self.pin_state_human(pin, active_low)
                label = rpi_output["label"]
                resp.append(
                    {
                        "Configured_As": configured_as,
                        "label": label,
                        "GPIO_Pin": pin,
                        "Active_Low": active_low,
                        "State": val,
                    },
                )
        if not match_found:
            pin = int(identifier)
            configured_as = "Unknown"
            active_low = "Unknown"
            try:
                val = self._gpio.input(pin)
            except Exception:
                val = "GPIO pin not initialized."
            resp.append({"Configured_As": configured_as, "GPIO_Pin": pin, "Active_Low": active_low, "State": val})
        return jsonify(resp)

    @octoprint.plugin.BlueprintPlugin.route("/inputs", methods=["GET"])
    def get_inputs(self):
        inputs = []
        for rpi_input in self.rpi_inputs:
            index = to_int(rpi_input["index_id"])
            label = rpi_input["label"]
            active_low = rpi_input["input_pull_resistor"] == PullResistor.UP.value
            pin = to_int(rpi_input["gpio_pin"])
            val = self.pin_state_human(pin, active_low)
            inputs.append({"index_id": index, "label": label, "GPIO_Pin": pin, "State": val})
        return jsonify(inputs)

    @octoprint.plugin.BlueprintPlugin.route("/inputs/<int:identifier>", methods=["GET"])
    def get_input_status(self, identifier):
        for rpi_input in self.rpi_inputs:
            if identifier == to_int(rpi_input["index_id"]):
                out = copy.deepcopy(rpi_input)
                # In previous versions, the automation of a GPIO input was saved in the rpi_input dict. To keep backward
                # compatibility, the API returns the input with the keys of its first automation, and the type of the
                # reaction in action_type. A filament sensor, a rule that stops the temperature controls and a rule
                # that runs a printer action were a printer_control with "filament", "stop_temp_hum_control" or the
                # command in printer_action, and a rule that runs another action was an output_control with the id of
                # the action in controlled_io.
                automation_settings = next(
                    (
                        item
                        for item in self.automations
                        if (item["automation_type"] == "filament" or item["trigger_type"] == "gpio_input")
                        and to_int(item["input"]) == identifier
                    ),
                    None,
                )
                if automation_settings is not None:
                    input_keys = (
                        "edge",
                        "controlled_io",
                        "controlled_io_set_state",
                        "filament_sensor_enabled",
                        "filament_sensor_timeout",
                    )
                    out.update({key: automation_settings[key] for key in input_keys if key in automation_settings})
                    out["printer_action"] = ""
                    if automation_settings["automation_type"] == "filament":
                        out["action_type"] = "printer_control"
                        out["printer_action"] = "filament"
                    elif automation_settings["reaction_type"] == "stop_temp_hum_control":
                        out["action_type"] = "printer_control"
                        out["printer_action"] = "stop_temp_hum_control"
                    elif automation_settings["reaction_type"] == "run_action":
                        action_settings = self.get_action_settings(to_int(automation_settings["action"]))
                        if action_settings is not None and action_settings["action_type"] == "printer":
                            out["action_type"] = "printer_control"
                            out["printer_action"] = action_settings["printer_action"]
                        else:
                            out["action_type"] = "output_control"
                            out["controlled_io"] = automation_settings["action"]
                    else:
                        out["action_type"] = automation_settings["reaction_type"]
                return jsonify(out)
        return make_response("", 404)

    @octoprint.plugin.BlueprintPlugin.route("/temperature/<int:identifier>", methods=["PATCH"])
    @restricted_access
    def set_enclosure_temp_humidity(self, identifier):
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "temperature" not in data:
            return make_response("missing temperature attribute", 406)

        set_value = data["temperature"]

        self.set_temp_hum_control_target(identifier, set_value)

        self.handle_temp_hum_control()
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/filament/<int:identifier>", methods=["PATCH"])
    @restricted_access
    def set_filament_sensor(self, identifier):
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "status" not in data:
            return make_response("missing status attribute", 406)

        value = data["status"]

        for automation_settings in self.automations:
            if (
                automation_settings["automation_type"] == "filament"
                and to_int(automation_settings["input"]) == identifier
            ):
                automation_settings["filament_sensor_enabled"] = value
                with contextlib.suppress(AutomationError):
                    index_id = to_int(automation_settings["index_id"])
                    self._automations.get(index_id, FilamentAutomation).enabled = bool(value)
                self._logger.info("Setting filament sensor for input %s to : %s", str(identifier), value)
        self._enclosure_settings.automations = self.automations
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/outputs", methods=["GET"])
    def get_outputs(self):
        outputs = []
        for rpi_output in self.rpi_outputs:
            if rpi_output["output_type"] == "regular":
                index = to_int(rpi_output["index_id"])
                label = rpi_output["label"]
                pin = to_int(rpi_output["gpio_pin"])
                val = self.output_state_human(index, RegularOutput)
                outputs.append({"index_id": index, "label": label, "GPIO_Pin": pin, "State": val})
        return jsonify(outputs)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:identifier>", methods=["GET"])
    def get_output_status(self, identifier):
        out = self.get_legacy_output_settings(identifier)
        if out is None:
            return make_response("", 404)
        if out["output_type"] == "pwm":
            with contextlib.suppress(OutputError):
                out["duty_cycle"] = self._outputs.get(identifier, PwmOutput).duty_cycle
        if out["output_type"] == "temp_hum_control":
            with contextlib.suppress(OutputError):
                out["temp_ctr_set_value"] = self._outputs.get(identifier, TempHumControlOutput).target
        if out["output_type"] in ("regular", "temp_hum_control"):
            output_class = RegularOutput if out["output_type"] == "regular" else TempHumControlOutput
            out["current_value"] = self.output_state_boolean(identifier, output_class)
        else:
            out["current_value"] = self.pin_state_boolean(to_int(out.get("gpio_pin")), False)
        return jsonify(out)

    # In previous versions, actions and temperature alarms were outputs, and PWM outputs linked to the temperature held
    # their curve, with pwm_temperature_linked on. To keep backward compatibility, the API returns them as they were
    # saved among the outputs, with their type in output_type.
    def get_legacy_output_settings(self, index_id):
        rpi_output = self.get_output_settings(index_id)
        if rpi_output is not None:
            out = copy.deepcopy(rpi_output)
            linked_settings = next(iter(self.get_pwm_temperature_linked_settings(index_id)), None)
            if out["output_type"] == "pwm":
                out["pwm_temperature_linked"] = linked_settings is not None
            if out["output_type"] == "pwm" and linked_settings is not None:
                linked_keys = ("linked_temp_sensor", "temperature_a", "duty_a", "temperature_b", "duty_b")
                out.update({key: linked_settings[key] for key in linked_keys})
            return out

        action_settings = self.get_action_settings(index_id)
        if action_settings is not None and action_settings["action_type"] != "printer":
            out = copy.deepcopy(action_settings)
            out["output_type"] = out.pop("action_type")
            return out

        alarm_settings = next(
            (
                item
                for item in self.automations
                if to_int(item["index_id"]) == index_id
                and item["automation_type"] == "rule"
                and item["trigger_type"] == "temperature"
                and item["reaction_type"] == "output_control"
            ),
            None,
        )
        if alarm_settings is not None:
            out = copy.deepcopy(alarm_settings)
            for key in ("automation_type", "trigger_type", "reaction_type"):
                del out[key]
            out["output_type"] = "temperature_alarm"
            return out

        return None

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:identifier>", methods=["PATCH"])
    @restricted_access
    def set_io(self, identifier):
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "status" not in data:
            return make_response("missing status attribute", 406)

        value = data["status"]

        for rpi_output in self.rpi_outputs:
            if identifier == to_int(rpi_output["index_id"]):
                self.switch_output(identifier, RegularSetState.ON if value else RegularSetState.OFF)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:identifier>/auto-startup", methods=["PATCH"])
    @restricted_access
    def set_auto_startup(self, identifier):
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "status" not in data:
            return make_response("missing status attribute", 406)

        value = data["status"]

        if not value:
            suffix = "auto_startup"
            queue_id = f"{identifier}_{suffix}"
            self.stop_queue_item(queue_id)
        for output in self.rpi_outputs:
            if identifier == to_int(output["index_id"]):
                output["auto_startup"] = value
                self._logger.info("Setting auto startup for output %s to : %s", str(identifier), value)
        self._enclosure_settings.rpi_outputs = self.rpi_outputs
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:identifier>/auto-shutdown", methods=["PATCH"])
    @restricted_access
    def set_auto_shutdown(self, identifier):
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "status" not in data:
            return make_response("missing status attribute", 406)

        value = data["status"]

        if not value:
            suffix = "auto_shutdown"
            queue_id = f"{identifier}_{suffix}"
            self.stop_queue_item(queue_id)

        for output in self.rpi_outputs:
            if identifier == to_int(output["index_id"]):
                output["auto_shutdown"] = value
                self._logger.info("Setting auto shutdown for output %s to : %s", str(identifier), value)
        self._enclosure_settings.rpi_outputs = self.rpi_outputs
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/pwm/<int:identifier>", methods=["PATCH"])
    @restricted_access
    def set_pwm(self, identifier):
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "duty_cycle" not in data:
            return make_response("missing duty_cycle attribute", 406)

        set_value = to_int(data["duty_cycle"])
        for rpi_output in [item for item in self.rpi_outputs if item["index_id"] == identifier]:
            rpi_output["new_duty_cycle"] = ""
            self.write_pwm(identifier, set_value)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/rgb-led/<int:identifier>", methods=["PATCH"])
    @restricted_access
    def set_ledstrip_color(self, identifier):
        """Set the color of the Open-Smart RGB LED Strip output with the given index."""
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "rgb" not in data:
            return make_response("missing rgb attribute", 406)
        rgb = data["rgb"]

        for rpi_output in self.rpi_outputs:
            if identifier == to_int(rpi_output["index_id"]):
                self.ledstrip_set_rgb(rpi_output, rgb)

        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/neopixel/<int:identifier>", methods=["PATCH"])
    @restricted_access
    def set_neopixel(self, identifier):
        """Set the color of the NeoPixel output with the given index."""
        if "application/json" not in request.headers["Content-Type"]:
            return make_response("expected json", 400)
        try:
            data = request.json
        except BadRequest:
            return make_response("malformed request", 400)

        if "red" not in data:
            return make_response("missing red attribute", 406)
        if "green" not in data:
            return make_response("missing green attribute", 406)
        if "blue" not in data:
            return make_response("missing blue attribute", 406)

        for rpi_output in self.rpi_outputs:
            if identifier == to_int(rpi_output["index_id"]):
                self.send_neopixel_command(rpi_output, data["red"], data["green"], data["blue"])

        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/clear-gpio", methods=["POST"])
    @restricted_access
    def clear_gpio_mode(self):
        self._gpio.cleanup()
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/update", methods=["POST"])
    @restricted_access
    def update_ui_requested(self):
        self.update_ui()
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/shell/<int:identifier>", methods=["POST"])
    @restricted_access
    def send_shell_command(self, identifier):
        self.run_action(identifier, ShellAction)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/gcode/<int:identifier>", methods=["POST"])
    @restricted_access
    def requested_gcode_command(self, identifier):
        self.run_action(identifier, GcodeAction)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/printer/<int:identifier>", methods=["POST"])
    @restricted_access
    def send_printer_command(self, identifier):
        self.run_action(identifier, PrinterAction)
        return make_response("", 204)

    def send_neopixel_command(self, output, red, green, blue, queue_id=None):
        """Send neopixel command.

        Args:
            output (dict): NeoPixel output whose color is being set.
            red (int): Red value from 0 to 255.
            green (int): Green value from 0 to 255.
            blue (int): Blue value from 0 to 255.
            queue_id (str, optional): Scheduled queue item to remove after sending the command.

        """
        index_id = output["index_id"]
        try:
            output["neopixel_color"] = f"rgb({red},{green},{blue})"

            if queue_id is not None:
                self._logger.debug("running scheduled queue id %s", queue_id)

            neopixel_class = (
                NeopixelDirectOutput if output["output_type"] == "neopixel_direct" else NeopixelIndirectOutput
            )
            self._outputs.get(index_id, neopixel_class).set_color(int(red), int(green), int(blue))

            if queue_id is not None:
                self.stop_queue_item(queue_id)
        except OutputError as error:
            self._logger.debug("Can't set the color of output %s: %s", index_id, error)
        except Exception:
            self._logger.exception("Error sending neopixel command for output %s", index_id)

    def configure_outputs(self):
        self._outputs = Outputs(self.rpi_outputs, self._gpio, self._i2c, self._logger)
        for rpi_output in self.rpi_outputs:
            if rpi_output["output_type"] == "temp_hum_control":
                self.set_temp_hum_control_target(to_int(rpi_output["index_id"]), rpi_output.get("temp_ctr_set_value"))

    def configure_gpio_inputs(self):
        gpio_inputs = [rpi_input for rpi_input in self.rpi_inputs if rpi_input["input_type"] == "gpio"]
        self._gpio_inputs = GpioInputs(gpio_inputs, self._gpio, self.handle_gpio_input, self._logger)

    def configure_actions(self):
        self._actions = Actions(self.actions, self._printer, self._frontend, self._logger)

    def configure_automations(self):
        self._automations = Automations(self.automations, self._logger)

    def get_output_settings(self, index_id):
        return next((item for item in self.rpi_outputs if to_int(item["index_id"]) == index_id), None)

    def get_action_settings(self, index_id):
        return next((item for item in self.actions if to_int(item["index_id"]) == index_id), None)

    def get_pwm_temperature_linked_settings(self, output_id=None):
        return [
            item
            for item in self.automations
            if item["automation_type"] == "pwm_temperature_linked"
            and (output_id is None or to_int(item["output"]) == output_id)
        ]

    def is_pwm_linked(self, index_id):
        return bool(self.get_pwm_temperature_linked_settings(to_int(index_id)))

    def get_sensor_inputs(self):
        return [rpi_input for rpi_input in self.rpi_inputs if rpi_input["input_type"] == "temperature_sensor"]

    def configure_sensors(self):
        self._sensors = Sensors(self.get_sensor_inputs(), self._logger, dummy=self.development_mode)
        if self.development_mode:
            self.link_dummy_sensors()

    def link_dummy_sensors(self):
        for control in self._outputs.get_all(TempHumControlOutput):
            try:
                dummy = self._sensors.get_dummy(control.config.linked_temp_sensor)
            except LookupError:
                continue
            if control.config.temp_ctr_type is TempHumControlType.HEATER:
                dummy.is_heater_on = control.is_on
            elif control.config.temp_ctr_type is TempHumControlType.COOLER:
                dummy.is_cooler_on = control.is_on
            elif control.config.temp_ctr_type is TempHumControlType.DEHUMIDIFIER:
                dummy.is_dehumidifier_on = control.is_on

    def check_enclosure_temp(self):
        try:
            with self.sensors_lock:
                sensor_inputs = self.get_sensor_inputs()
                sensors = self._sensors

            sensor_data = []
            for sensor in sensor_inputs:
                try:
                    reading = sensors.read(sensor["index_id"])
                except Exception as error:
                    self.handle_sensor_failure(sensor, error)
                    sensor["temp_sensor_temp"] = ""
                    sensor["temp_sensor_humidity"] = ""
                    temp = hum = airquality = None
                else:
                    temp, hum, airquality = self.convert_reading(sensor, reading)
                    self.handle_sensor_recovery(sensor)
                    sensor["temp_sensor_temp"] = "" if temp is None else temp
                    sensor["temp_sensor_humidity"] = "" if hum is None else hum
                    self._mqtt.publish_sensor_reading(sensor["label"], temp, hum)

                sensor_data.append(
                    {
                        "index_id": sensor["index_id"],
                        "temperature": temp,
                        "humidity": hum,
                        "airquality": airquality,
                    },
                )

            if sensor_data:
                self.temperature_sensor_data = sensor_data
                self.handle_temp_hum_control()
                self.handle_temperature_rules()
                self.handle_pwm_linked_temperature()
                self.update_ui()
        except Exception:
            self._logger.exception("Error checking enclosure temperature")

    def handle_sensor_failure(self, sensor, error):
        if sensor["index_id"] in self.failing_sensors:
            self._logger.debug("Sensor %s still can't be read: %s", sensor["label"], error)
            return

        self.failing_sensors.add(sensor["index_id"])
        self._logger.error(
            "Sensor %s can't be read: %s",
            sensor["label"],
            error,
            exc_info=not isinstance(error, SensorError),
        )

        for rule in self._automations.get_all(RuleAutomation):
            trigger = rule.trigger
            if isinstance(trigger, TemperatureTrigger) and trigger.config.linked_temp_sensor == sensor["index_id"]:
                self._notifications.send(
                    NotificationType.TEMPERATURE_ACTION,
                    f"Temperature alarm: sensor {sensor['label']} can't be read",
                )

    def handle_sensor_recovery(self, sensor):
        if sensor["index_id"] in self.failing_sensors:
            self.failing_sensors.remove(sensor["index_id"])
            self._logger.info("Sensor %s has started working again", sensor["label"])

    def toggle_output(self, output_index, first_run=False):
        for output in [item for item in self.rpi_outputs if item["index_id"] == output_index]:
            index_id = to_int(output["index_id"])

            if output["output_type"] == "regular":
                if not self.print_complete:
                    on = self.switch_output(index_id, RegularSetState.ON if first_run else RegularSetState.TOGGLE)
                    time_delay = to_int(output["toggle_timer_on"]) if on else to_int(output["toggle_timer_off"])
                    thread = threading.Timer(time_delay, self.toggle_output, args=[index_id])
                    thread.start()
                else:
                    self.switch_output(index_id, RegularSetState.OFF)
                self.update_ui_outputs()
                return

            if output["output_type"] == "pwm":
                try:
                    pwm_output = self._outputs.get(index_id, PwmOutput)
                except OutputError as error:
                    self._logger.debug("Can't toggle output %s: %s", index_id, error)
                    return

                current_pwm_value = 0 if first_run else to_int(pwm_output.duty_cycle)

                if current_pwm_value != 0:
                    time_delay = to_int(output["toggle_timer_off"])
                    write_value = 0
                else:
                    time_delay = to_int(output["toggle_timer_on"])
                    write_value = to_int(output["default_duty_cycle"])

                if not self.print_complete:
                    self.write_pwm(index_id, write_value)
                    thread = threading.Timer(time_delay, self.toggle_output, args=[index_id])
                    thread.start()
                else:
                    self.write_pwm(index_id, 0)
                self.update_ui_outputs()
                return

    def update_ui(self):
        self.update_ui_outputs()
        self.update_ui_current_temperature()
        self.update_ui_set_temperature()
        self.update_ui_inputs()

    def update_ui_current_temperature(self):
        self._frontend.update_sensor_data(self.temperature_sensor_data)

    def update_ui_set_temperature(self):
        result = []
        for temp_crt_output in list(filter(lambda item: item["output_type"] == "temp_hum_control", self.rpi_outputs)):
            with contextlib.suppress(OutputError):
                set_temperature = self._outputs.get(to_int(temp_crt_output["index_id"]), TempHumControlOutput).target
                result.append({"index_id": temp_crt_output["index_id"], "set_temperature": set_temperature})
                result.append(set_temperature)
        self._frontend.update_set_temperature(result)

    def stop_queue_item(self, queue_id):
        old_list = self.event_queue
        self._logger.debug("Stopping queue id %s...", queue_id)
        for task in self.event_queue:
            self._logger.debug("Queue id found...")
            if task["queue_id"] == queue_id:
                task["thread"].cancel()
                self.event_queue.remove(task)
                self._logger.debug("Queue id stopped and removed from list...")
                self._logger.debug("Old queue list: %s", old_list)
                self._logger.debug("New queue list: %s", self.event_queue)

    def update_ui_outputs(self):
        try:
            regular_status = []
            pwm_status = []
            neopixel_status = []
            ledstrip_status = []
            temp_control_status = []
            for output in self.rpi_outputs:
                index = to_int(output["index_id"])
                startup = output["auto_startup"]
                shutdown = output["auto_shutdown"]

                if output["output_type"] == "regular":
                    val = self.output_state_boolean(index, RegularOutput) is True
                    regular_status.append(
                        {"index_id": index, "status": val, "auto_startup": startup, "auto_shutdown": shutdown},
                    )
                if output["output_type"] == "temp_hum_control":
                    val = self.output_state_boolean(index, TempHumControlOutput) is True
                    temp_control_status.append(
                        {"index_id": index, "status": val, "auto_startup": startup, "auto_shutdown": shutdown},
                    )
                if output["output_type"] == "neopixel_indirect" or output["output_type"] == "neopixel_direct":
                    val = output["neopixel_color"]
                    neopixel_status.append(
                        {"index_id": index, "color": val, "auto_startup": startup, "auto_shutdown": shutdown},
                    )
                if output["output_type"] == "ledstrip":
                    val = output["ledstrip_color"]
                    ledstrip_status.append(
                        {"index_id": index, "color": val, "auto_startup": startup, "auto_shutdown": shutdown},
                    )
                if output["output_type"] == "pwm":
                    with contextlib.suppress(OutputError):
                        val = to_int(self._outputs.get(index, PwmOutput).duty_cycle)
                        pwm_status.append(
                            {
                                "index_id": index,
                                "pwm_value": val,
                                "auto_startup": startup,
                                "auto_shutdown": shutdown,
                            },
                        )
            self._frontend.update_outputs(
                regular=regular_status,
                pwm=pwm_status,
                neopixel=neopixel_status,
                ledstrip=ledstrip_status,
                temp_hum_ctrl=temp_control_status,
            )
        except Exception:
            self._logger.exception("Error sending outputs status to the UI")

    def update_ui_inputs(self):
        try:
            sensor_status = []
            for automation_settings in self.automations:
                if automation_settings["automation_type"] == "filament":
                    index = to_int(automation_settings["index_id"])
                    with contextlib.suppress(AutomationError):
                        value = self._automations.get(index, FilamentAutomation).enabled
                        sensor_status.append({"index_id": index, "filament_sensor_enabled": value})
            self._frontend.update_filament_sensor_status(sensor_status)
        except Exception:
            self._logger.exception("Error sending input status to the UI")

    def convert_reading(self, sensor, reading):
        temperature = reading.temperature
        if temperature is not None and sensor["use_fahrenheit"]:
            temperature = temperature * 1.8 + 32

        temperature = None if temperature is None else round(float(temperature), 1)
        humidity = None if reading.humidity is None else round(float(reading.humidity), 1)
        airquality = None if reading.airquality is None else round(float(reading.airquality), 1)

        return temperature, humidity, airquality

    def handle_temperature_rules(self):
        for rule in self._automations.get_all(RuleAutomation):
            trigger = rule.trigger
            if not isinstance(trigger, TemperatureTrigger):
                continue
            linked_data = self.get_linked_temp_sensor_data(trigger.config.linked_temp_sensor)
            temperature = None if linked_data is None else linked_data["temperature"]
            if trigger.matches_temperature(temperature):
                self.handle_temperature_reaction(rule.reaction, trigger.config.alarm_set_temp)

    def handle_pwm_linked_temperature(self):
        try:
            for pwm_linked in self._automations.get_all(PwmTemperatureLinkedAutomation):
                output_id = pwm_linked.config.output
                if self._printer.is_printing():
                    linked_data = self.get_linked_temp_sensor_data(pwm_linked.config.linked_temp_sensor)
                    temperature = None if linked_data is None else linked_data["temperature"]
                    calculated_duty = pwm_linked.get_duty_cycle(temperature)
                    self._logger.debug("Calculated duty for PWM %s is %s", output_id, calculated_duty)
                elif self.print_complete:
                    # After a print the PWM keeps its duty cycle: the default one, or the one set through API or ENC
                    continue
                else:
                    calculated_duty = 0

                self.write_pwm(output_id, calculated_duty)

        except Exception:
            self._logger.exception("Error handling temperature linked PWM outputs")

    def get_linked_temp_sensor_data(self, linked_id):
        linked_data = next((data for data in self.temperature_sensor_data if data["index_id"] == linked_id), None)
        if linked_data is None:
            self._logger.warning("No linked temperature sensor found for %s", linked_id)
        return linked_data

    def handle_temp_hum_control(self):
        try:
            for temp_hum_control in list(
                filter(lambda item: item["output_type"] == "temp_hum_control", self.rpi_outputs),
            ):
                index_id = to_int(temp_hum_control["index_id"])
                try:
                    control = self._outputs.get(index_id, TempHumControlOutput)
                except OutputError:
                    continue

                # With a target of 0 the control is off, and doesn't need the sensor
                if control.target == 0:
                    linked_sensor_data = None
                else:
                    linked_sensor_data = self.get_linked_temp_sensor_data(control.config.linked_temp_sensor)
                temperature = None if linked_sensor_data is None else linked_sensor_data["temperature"]
                humidity = None if linked_sensor_data is None else linked_sensor_data["humidity"]

                previous_status = control.status
                try:
                    status = control.regulate(temperature, humidity)
                except Exception:
                    self._logger.exception("Error reading or writing output %s", index_id)
                    continue
                if status is previous_status:
                    continue

                # A print paused by ENC W1 goes on when no control it waits for still has to reach its target
                if status is TempHumControlStatus.IDLE and index_id in self.waiting_temperature:
                    self.waiting_temperature.discard(index_id)
                    if not self.waiting_temperature and self._printer.is_paused():
                        self._printer.resume_print()

                self.update_ui()
        except Exception:
            self._logger.exception("Error handling temperature/humidity control")

    def setup_gpio(self):
        try:
            current_mode = self._gpio.getmode()
            set_mode = self._gpio.BOARD if self._enclosure_settings.use_board_pin_number else self._gpio.BCM
            if current_mode is None:
                outputs = list(
                    filter(
                        lambda item: (
                            (
                                item["output_type"] == "regular"
                                or item["output_type"] == "pwm"
                                or item["output_type"] == "temp_hum_control"
                                or item["output_type"] == "neopixel_direct"
                            )
                            and not item["gpio_i2c_enabled"]
                        ),
                        self.rpi_outputs,
                    ),
                )
                inputs = list(filter(lambda item: item["input_type"] == "gpio", self.rpi_inputs))
                gpios = outputs + inputs
                if gpios:
                    self._gpio.setmode(set_mode)
                    tempstr = "BOARD" if set_mode == self._gpio.BOARD else "BCM"
                    self._logger.info("Setting GPIO mode to %s", tempstr)
            elif current_mode != set_mode:
                self._gpio.setmode(current_mode)
                tempstr = "BOARD" if current_mode == self._gpio.BOARD else "BCM"
                self._enclosure_settings.use_board_pin_number = current_mode == self._gpio.BOARD
                warn_msg = (
                    "GPIO mode was configured before, GPIO mode will be forced to use: "
                    + tempstr
                    + " as pin numbers. Please update GPIO accordingly!"
                )
                self._logger.info(warn_msg)
                self._frontend.show_message(warn_msg, "error")
            self._gpio.setwarnings(False)
        except Exception:
            self._logger.exception("Error setting up GPIO mode")

    def clear_gpio(self):
        try:
            for gpio_out in list(
                filter(
                    lambda item: (
                        (
                            item["output_type"] == "regular"
                            or item["output_type"] == "pwm"
                            or item["output_type"] == "temp_hum_control"
                            or item["output_type"] == "neopixel_direct"
                        )
                        and not item["gpio_i2c_enabled"]
                    ),
                    self.rpi_outputs,
                ),
            ):
                gpio_pin = to_int(gpio_out["gpio_pin"])
                if gpio_pin not in self.rpi_outputs_not_changed:
                    self._gpio.cleanup(gpio_pin)

            self._gpio_inputs.clear()
        except Exception:
            self._logger.exception("Error clearing GPIO")

    def clear_channel(self, channel):
        try:
            self._gpio.cleanup(to_int(channel))
            self._logger.debug("Clearing channel %s", channel)
        except Exception:
            self._logger.exception("Error clearing channel %s", channel)

    def configure_gpio(self):
        try:
            for regular_output in self._outputs.get_all(RegularOutput):
                if regular_output.config.gpio_pin not in self.rpi_outputs_not_changed:
                    regular_output.setup_pin()
            for temp_hum_control in self._outputs.get_all(TempHumControlOutput):
                if temp_hum_control.config.gpio_pin not in self.rpi_outputs_not_changed:
                    temp_hum_control.setup_pin()
            for pwm_output in self._outputs.get_all(PwmOutput):
                pwm_output.start()
            for neopixel_output in self._outputs.get_all(NeopixelDirectOutput):
                self.clear_channel(neopixel_output.config.gpio_pin)

            self._gpio_inputs.setup_pins(self._automations.get_gpio_input_edges())

            for rpi_input in self.get_sensor_inputs():
                gpio_pin = to_int(rpi_input["gpio_pin"])
                if rpi_input["input_pull_resistor"] == "input_pull_up":
                    pull_resistor = self._gpio.PUD_UP
                elif rpi_input["input_pull_resistor"] == "input_pull_down":
                    pull_resistor = self._gpio.PUD_DOWN
                else:
                    pull_resistor = self._gpio.PUD_OFF
                self._gpio.setup(gpio_pin, self._gpio.IN, pull_up_down=pull_resistor)
        except Exception:
            self._logger.exception("Error configuring GPIO")

    def handle_filament_detection(self, automation, input_id, input_label):
        try:
            if automation.detect_end():
                gcode_logger = self._logger.getChild("Actions.GcodeAction")
                gcode_config = GcodeConfig(self._enclosure_settings.filament_sensor_gcode)
                GcodeAction(gcode_config, self._printer, self._frontend, gcode_logger).run()
                self._notifications.send(
                    NotificationType.FILAMENT_CHANGE,
                    f"Filament change action caused by sensor: {input_label}",
                )
        except Exception:
            self._logger.exception("Error handling filament detection of input %s", input_id)

    def start_filament_detection(self):
        self.stop_filament_detection()
        try:
            for filament_automation in self._automations.get_all(FilamentAutomation):
                input_id = filament_automation.trigger.config.input
                try:
                    level = self._gpio_inputs.get(input_id).read_pin_level()
                except GpioInputError as error:
                    self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                    continue
                if filament_automation.is_filament_missing(level):
                    self._printer.pause_print()
                    self._logger.info("Started printing with no filament.")
                else:
                    filament_automation.arm()
        except Exception:
            self._logger.exception("Error starting filament detection")

    def stop_filament_detection(self):
        for filament_automation in self._automations.get_all(FilamentAutomation):
            filament_automation.disarm()

    def cancel_all_events_on_queue(self):
        for task in self.event_queue:
            try:
                task["thread"].cancel()
            except Exception:
                self._logger.exception("Failed to stop task %s", task)

    def handle_initial_gpio_control(self):
        try:
            for rule in self._automations.get_all(RuleAutomation):
                trigger, reaction = rule.trigger, rule.reaction
                if not isinstance(trigger, GpioInputTrigger) or not isinstance(reaction, OutputControlReaction):
                    continue
                input_id = trigger.config.input
                try:
                    level = self._gpio_inputs.get(input_id).read_pin_level()
                except GpioInputError as error:
                    self._logger.debug("Can't read GPIO input %s: %s", input_id, error)
                    continue
                if trigger.matches_level(level):
                    self.control_output(reaction.config)
        except Exception:
            self._logger.exception("Error handling initial GPIO control")

    def run_action(self, index_id, action_class):
        try:
            action = self._actions.get(index_id, action_class)
        except ActionError as error:
            self._logger.debug("Can't run action %s: %s", index_id, error)
            return
        action.run()

    def handle_gpio_input(self, input_id, level):
        input_label = next(
            (rpi_input["label"] for rpi_input in self.rpi_inputs if to_int(rpi_input["index_id"]) == input_id),
            "",
        )
        for automation in self._automations.get_triggered_by_gpio_input(input_id, level):
            if isinstance(automation, RuleAutomation):
                self.handle_gpio_reaction(automation.reaction, input_id, input_label)
            elif isinstance(automation, FilamentAutomation):
                self.handle_filament_detection(automation, input_id, input_label)

    def handle_gpio_reaction(self, reaction, input_id, input_label):
        try:
            if isinstance(reaction, OutputControlReaction):
                config = reaction.config
                if self.control_output(config):
                    self._notifications.send(
                        NotificationType.GPIO_ACTION,
                        f"GPIO control action caused by input {input_label}. "
                        f"Setting GPIO{config.controlled_io} to: {config.controlled_io_set_state.value}",
                    )
            elif isinstance(reaction, RunActionReaction):
                action_settings = self.run_automation_action(reaction.config.action)
                action_type = action_settings.get("action_type")
                if action_type == "gcode_output":
                    self._notifications.send(
                        NotificationType.GPIO_ACTION,
                        f"GPIO control action caused by input {input_label}. Sending GCODE command",
                    )
                elif action_type == "printer":
                    self._notifications.send(
                        NotificationType.PRINTER_ACTION,
                        f"Printer action: {action_settings['printer_action']} caused by input: {input_label}",
                    )
            elif isinstance(reaction, StopTempHumControlReaction):
                self.stop_temp_hum_control()
                self._notifications.send(
                    NotificationType.PRINTER_ACTION,
                    f"Printer action: stop_temp_hum_control caused by input: {input_label}",
                )
        except Exception:
            self._logger.exception("Error handling an automation of input %s", input_id)

    def handle_temperature_reaction(self, reaction, threshold):
        cause = f"enclosure temperature exceed {threshold:g}"
        try:
            if isinstance(reaction, OutputControlReaction):
                if self.control_output(reaction.config):
                    self._notifications.send(NotificationType.TEMPERATURE_ACTION, f"Temperature action: {cause}")
            elif isinstance(reaction, RunActionReaction):
                action_settings = self.run_automation_action(reaction.config.action)
                action_type = action_settings.get("action_type")
                if action_type == "gcode_output":
                    self._notifications.send(NotificationType.TEMPERATURE_ACTION, f"Temperature action: {cause}")
                elif action_type == "printer":
                    self._notifications.send(
                        NotificationType.PRINTER_ACTION,
                        f"Printer action: {action_settings['printer_action']} caused by {cause}",
                    )
            elif isinstance(reaction, StopTempHumControlReaction):
                self.stop_temp_hum_control()
                self._notifications.send(
                    NotificationType.PRINTER_ACTION,
                    f"Printer action: stop_temp_hum_control caused by {cause}",
                )
        except Exception:
            self._logger.exception("Error handling an automation on the temperature above %s", threshold)

    def control_output(self, config):
        output_settings = self.get_output_settings(config.controlled_io)
        if output_settings is None or output_settings["output_type"] != "regular":
            return False
        self.switch_output(config.controlled_io, config.controlled_io_set_state)
        return True

    def run_automation_action(self, index_id):
        action_settings = self.get_action_settings(index_id)
        if action_settings is None:
            return {}
        try:
            self._actions.run(index_id)
        except ActionError as error:
            self._logger.debug("Can't run action %s: %s", index_id, error)
        return action_settings

    def stop_temp_hum_control(self):
        self._logger.info("Printer action stopping temperature control.")
        for rpi_output in self.rpi_outputs:
            if rpi_output["auto_shutdown"] and rpi_output["output_type"] == "temp_hum_control":
                self.set_temp_hum_control_target(to_int(rpi_output["index_id"]), 0)
        self.handle_temp_hum_control()

    def set_temp_hum_control_target(self, index_id, target):
        try:
            self._outputs.get(index_id, TempHumControlOutput).set_target(to_float(target))
        except OutputError as error:
            self._logger.debug("Can't set the target of output %s: %s", index_id, error)

    def switch_output(self, index_id, state, queue_id=None):
        try:
            regular_output = self._outputs.get(index_id, RegularOutput)
            if state is RegularSetState.TOGGLE:
                on = regular_output.toggle()
            elif state is RegularSetState.ON:
                regular_output.turn_on()
                on = True
            else:
                regular_output.turn_off()
                on = False
            if queue_id is not None:
                self._logger.debug("Running scheduled queue id %s", queue_id)
            self.update_ui()
            if queue_id is not None:
                self.stop_queue_item(queue_id)
        except OutputError as error:
            self._logger.debug("Can't write on output %s: %s", index_id, error)
            return None
        except Exception:
            self._logger.exception("Error writing on output %s", index_id)
            return None
        else:
            return on

    def write_pwm(self, index_id, pwm_value, queue_id=None):
        try:
            if queue_id is not None:
                self._logger.debug("running scheduled queue id %s", queue_id)
            self._outputs.get(index_id, PwmOutput).set_duty_cycle(pwm_value)
            self.update_ui()
            if queue_id is not None:
                self.stop_queue_item(queue_id)
        except OutputError as error:
            self._logger.debug("Can't write PWM on output %s: %s", index_id, error)
        except Exception:
            self._logger.exception("Error writing PWM on output %s", index_id)

    def get_output_list(self):
        return [
            to_int(rpi_output["gpio_pin"]) for rpi_output in self.rpi_outputs if rpi_output["output_type"] == "regular"
        ]

    # ~~ EventPlugin mixin
    def on_event(self, event, payload):
        if event == Events.CONNECTED:
            self.update_ui()

        if event == Events.CLIENT_OPENED:
            self.update_ui()

        if event == Events.PRINT_RESUMED:
            self.start_filament_detection()

        if event == Events.PRINT_STARTED:
            self.print_complete = False
            self.cancel_all_events_on_queue()
            self.event_queue = []
            self.start_filament_detection()
            for rpi_output in self.rpi_outputs:
                if rpi_output["auto_startup"]:
                    startup_time = rpi_output["startup_time"]
                    delay_seconds = (
                        seconds_until_today_at(startup_time) if is_hhmm(startup_time) else to_float(startup_time)
                    )
                    self.schedule_auto_startup_outputs(rpi_output, delay_seconds)
                if rpi_output["toggle_timer"] and rpi_output["output_type"] in ("regular", "pwm"):
                    self.toggle_output(rpi_output["index_id"], True)
                if is_hhmm(rpi_output["shutdown_time"]):
                    shutdown_delay_seconds = seconds_until_next(rpi_output["shutdown_time"])
                    self.schedule_auto_shutdown_outputs(rpi_output, shutdown_delay_seconds)
            self.run_tasks()
            self.update_ui()

        elif event == Events.PRINT_DONE:
            self.stop_filament_detection()
            self.print_complete = True
            for rpi_output in self.rpi_outputs:
                shutdown_time = rpi_output["shutdown_time"]
                if rpi_output["output_type"] == "pwm" and self.is_pwm_linked(rpi_output["index_id"]):
                    self.write_pwm(rpi_output["index_id"], to_int(rpi_output["default_duty_cycle"]))
                if rpi_output["auto_shutdown"] and not is_hhmm(shutdown_time):
                    delay_seconds = to_float(shutdown_time)
                    self.schedule_auto_shutdown_outputs(rpi_output, delay_seconds)
            self.run_tasks()
            self.update_ui()

        elif event in (Events.PRINT_CANCELLED, Events.PRINT_FAILED):
            self.stop_filament_detection()
            self.cancel_all_events_on_queue()
            self.event_queue = []
            for rpi_output in self.rpi_outputs:
                if rpi_output["shutdown_on_failed"]:
                    shutdown_time = rpi_output["shutdown_time"]
                    if rpi_output["auto_shutdown"] and not is_hhmm(shutdown_time):
                        delay_seconds = to_float(shutdown_time)
                        self.schedule_auto_shutdown_outputs(rpi_output, delay_seconds)
                        if rpi_output["output_type"] == "temp_hum_control":
                            self.set_temp_hum_control_target(to_int(rpi_output["index_id"]), 0)
            self.run_tasks()

        if event == Events.PRINT_DONE:
            file_name = Path(payload["path"]).name
            elapsed_time = octoprint.util.get_formatted_timedelta(timedelta(seconds=payload["time"]))
            self._notifications.send(
                NotificationType.PRINT_FINISH,
                f"Print job finished: {file_name} printed in {elapsed_time}",
            )

        if event in (Events.ERROR, Events.DISCONNECTED) or (
            event == Events.PRINTER_STATE_CHANGED and "error" in payload["state_string"].lower()
        ):
            self._logger.info("Detected %s, shutting down outputs with shutdown_on_error", event)
            for rpi_output in self.rpi_outputs:
                if rpi_output["shutdown_on_error"]:
                    self._logger.debug("Schedule shutdown for: %s", rpi_output["index_id"])
                    self.schedule_auto_shutdown_outputs(rpi_output, 0)
            self.run_tasks()

    def run_tasks(self):
        for task in self.event_queue:
            if not task["thread"].is_alive():
                task["thread"].start()

    def schedule_auto_shutdown_outputs(self, rpi_output, shutdown_delay_seconds):
        suffix = "auto_shutdown"
        if rpi_output["output_type"] == "regular":
            self.add_regular_output_to_queue(shutdown_delay_seconds, rpi_output, RegularSetState.OFF, suffix)
        if rpi_output["output_type"] == "ledstrip":
            self.ledstrip_set_rgb(rpi_output)
        if rpi_output["output_type"] == "pwm" and not self.is_pwm_linked(rpi_output["index_id"]):
            value = 0
            self.add_pwm_output_to_queue(shutdown_delay_seconds, rpi_output, value, suffix)
        if rpi_output["output_type"] == "pwm" and self.is_pwm_linked(rpi_output["index_id"]):
            self.schedule_pwm_duty_on_queue(shutdown_delay_seconds, rpi_output, 0, suffix)
        if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
            self.add_neopixel_output_to_queue(rpi_output, shutdown_delay_seconds, 0, 0, 0, suffix)
        if rpi_output["output_type"] == "temp_hum_control":
            value = 0
            self.add_temperature_output_temperature_queue(shutdown_delay_seconds, rpi_output, value, suffix)
        self._logger.debug("Events scheduled to run %s", self.event_queue)

    def ledstrip_set_rgb(self, rpi_output, rgb=None):
        try:
            ledstrip = self._outputs.get(rpi_output["index_id"], LedstripOutput)
        except OutputError as error:
            self._logger.debug("Can't set the color of output %s: %s", rpi_output["index_id"], error)
        else:
            if rgb is None:
                red, green, blue = parse_rgb(rpi_output["default_ledstrip_color"])
            else:
                red, green, blue = parse_rgb(rgb)

            self._logger.info("LEDSTRIP set rgb color: %s, %s, %s", red, green, blue)
            ledstrip.set_color(to_int(red), to_int(green), to_int(blue))
            rpi_output["ledstrip_color"] = f"rgb({red},{green},{blue})"

    def start_outpus_with_server(self):
        for rpi_output in self.rpi_outputs:
            if rpi_output["startup_with_server"]:
                if rpi_output["output_type"] == "regular":
                    self.switch_output(rpi_output["index_id"], RegularSetState.ON)
                if rpi_output["output_type"] == "ledstrip":
                    self.ledstrip_set_rgb(rpi_output)
                if rpi_output["output_type"] == "pwm" and not self.is_pwm_linked(rpi_output["index_id"]):
                    value = to_int(rpi_output["default_duty_cycle"])
                    self.write_pwm(rpi_output["index_id"], value)
                if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
                    red, green, blue = parse_rgb(rpi_output["default_neopixel_color"])
                    self.send_neopixel_command(rpi_output, red, green, blue)
                if rpi_output["output_type"] == "temp_hum_control":
                    index_id = to_int(rpi_output["index_id"])
                    self.set_temp_hum_control_target(index_id, rpi_output["temp_ctr_default_value"])

    def schedule_auto_startup_outputs(self, rpi_output, delay_seconds):
        suffix = "auto_startup"
        if rpi_output["output_type"] == "regular":
            self.add_regular_output_to_queue(delay_seconds, rpi_output, RegularSetState.ON, suffix)
        if rpi_output["output_type"] == "ledstrip":
            self.ledstrip_set_rgb(rpi_output)
        if rpi_output["output_type"] == "pwm" and not self.is_pwm_linked(rpi_output["index_id"]):
            value = to_int(rpi_output["default_duty_cycle"])
            self.add_pwm_output_to_queue(delay_seconds, rpi_output, value, suffix)
        if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
            red, green, blue = parse_rgb(rpi_output["default_neopixel_color"])
            self.add_neopixel_output_to_queue(rpi_output, delay_seconds, red, green, blue, suffix)
        if rpi_output["output_type"] == "temp_hum_control":
            value = rpi_output["temp_ctr_default_value"]
            self.add_temperature_output_temperature_queue(delay_seconds, rpi_output, value, suffix)
        self._logger.debug("Events scheduled to run %s", self.event_queue)

    def add_neopixel_output_to_queue(self, rpi_output, delay_seconds, red, green, blue, suffix):
        queue_id = f"{to_int(rpi_output['index_id'])}_{suffix}"

        self._logger.debug("Scheduling neopixel output id %s for on %s delay_seconds", queue_id, delay_seconds)

        thread = threading.Timer(
            delay_seconds,
            self.send_neopixel_command,
            args=[rpi_output, red, green, blue, queue_id],
        )

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def add_pwm_output_to_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"{rpi_output['index_id']}_{suffix}"

        self._logger.debug("Scheduling pwm output id %s for on %s delay_seconds", queue_id, delay_seconds)

        thread = threading.Timer(
            delay_seconds,
            self.write_pwm,
            args=[rpi_output["index_id"], value, queue_id],
        )

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def schedule_pwm_duty_on_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"{rpi_output['index_id']}_pwm_linked_temp_{suffix}"
        thread = threading.Timer(delay_seconds, self.write_pwm, args=[rpi_output["index_id"], value, queue_id])

        self._logger.debug("Scheduling pwm linked temp output id %s on %s delay_seconds", queue_id, delay_seconds)

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def add_regular_output_to_queue(self, delay_seconds, rpi_output, state, suffix):
        queue_id = f"{rpi_output['index_id']}_{suffix}"

        self._logger.debug("Scheduling regular output id %s on %s delay_seconds", queue_id, delay_seconds)

        thread = threading.Timer(delay_seconds, self.switch_output, args=[rpi_output["index_id"], state, queue_id])

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def add_temperature_output_temperature_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"{rpi_output['index_id']}_{suffix}"
        self._logger.debug("Scheduling temperature control id %s on %s delay_seconds", queue_id, delay_seconds)

        thread = threading.Timer(
            delay_seconds,
            self.write_temperature_to_output,
            args=[to_int(rpi_output["index_id"]), value, queue_id],
        )

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def write_temperature_to_output(self, rpi_output_index, value, queue_id=None):
        try:
            rpi_output = [r_out for r_out in self.rpi_outputs if to_int(r_out["index_id"]) == rpi_output_index].pop()

            if rpi_output["output_type"] == "temp_hum_control":
                self.set_temp_hum_control_target(rpi_output_index, value)

                if queue_id is not None:
                    self._logger.debug("running scheduled queue id %s", queue_id)
                self._logger.debug("Setting temperature to output index: %s value %s", rpi_output["index_id"], value)

            self.update_ui()
            if queue_id is not None:
                self.stop_queue_item(queue_id)

        except Exception:
            self._logger.exception("Error setting temperature on output %s", rpi_output_index)

    # ~~ SettingsPlugin mixin
    def on_settings_save(self, data):
        outputs_before_save = self.get_output_list()
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        for pwm_output in self._outputs.get_all(PwmOutput):
            pwm_output.stop()
        self.rpi_outputs = self._enclosure_settings.rpi_outputs
        self.configure_outputs()
        with self.sensors_lock:
            self.rpi_inputs = self._enclosure_settings.rpi_inputs
            self.configure_sensors()
        self.actions = self._enclosure_settings.actions
        self.configure_actions()
        self.automations = self._enclosure_settings.automations
        self.configure_automations()
        outputs_after_save = self.get_output_list()

        common_pins = list(set(outputs_before_save) & set(outputs_after_save))

        for pin in (pin for pin in outputs_before_save if pin not in common_pins):
            self.clear_channel(pin)

        self.rpi_outputs_not_changed = common_pins
        self.clear_gpio()
        self.configure_gpio_inputs()

        self._logger.debug("rpi_outputs: %s", self.rpi_outputs)
        self._logger.debug("rpi_inputs: %s", self.rpi_inputs)
        self.setup_gpio()
        self.configure_gpio()

    def get_settings_defaults(self):
        return {
            "rpi_outputs": [],
            "rpi_inputs": [],
            "actions": [],
            "automations": [],
            "filament_sensor_gcode": (
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
            ),
            "gcode_control": False,
            "use_board_pin_number": False,
            "notification_provider": "",
            "notification_api_key": "",
            "notification_event_name": "printer_event",
            "notifications": [{notification_type.value: True for notification_type in NotificationType}],
            "development_mode": False,
        }

    # ~~ TemplatePlugin
    def get_template_vars(self):
        gpio_import_error = gpio.get_import_error()
        return {
            "development_mode": self.development_mode,
            "gpio_import_error": str(gpio_import_error) if gpio_import_error is not None else None,
        }

    def get_template_configs(self):
        return [
            {"type": "settings", "custom_bindings": True},
            {"type": "tab", "custom_bindings": True},
            {"type": "navbar", "custom_bindings": True, "suffix": "_1", "classes": ["dropdown"]},
            {
                "type": "navbar",
                "custom_bindings": True,
                "template": "enclosure_navbar_input.jinja2",
                "suffix": "_2",
                "classes": ["dropdown"],
            },
        ]

    def is_template_autoescaped(self):
        return True

    # ~~ AssetPlugin mixin
    def get_assets(self):
        return {
            "js": ["js/enclosure.js"],
            "css": ["css/enclosure.css"],
        }

    # ~~ Softwareupdate hook
    def get_update_information(self):
        return {
            "enclosure": {
                "displayName": "Enclosure Plugin",
                "displayVersion": self._plugin_version,
                # version check: github repository
                "type": "github_release",
                "user": "jacopotediosi",
                "repo": "OctoPrint-Enclosure",
                "current": self._plugin_version,
                # update method: pip
                "pip": "https://github.com/jacopotediosi/OctoPrint-Enclosure/archive/{target_version}.zip",
            },
        }

    def hook_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        self._enc_handler.handle(comm_instance, cmd)

    def hook_atcommand_queuing(self, comm_instance, phase, command, parameters, tags=None, *args, **kwargs):
        self._encdev_handler.handle(comm_instance, command, parameters)

    def get_graph_data(self, comm, parsed_temps):
        for sensor in self.get_sensor_inputs():
            if sensor["show_graph_temp"] and sensor["temp_sensor_temp"] != "":
                parsed_temps[str(sensor["label"])] = (sensor["temp_sensor_temp"], None)
            if sensor["show_graph_humidity"] and sensor["temp_sensor_humidity"] != "":
                parsed_temps[str(sensor["label"]) + " Humidity"] = (sensor["temp_sensor_humidity"], None)

        return parsed_temps
