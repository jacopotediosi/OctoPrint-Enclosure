import contextlib
import copy
import math
import struct
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from subprocess import PIPE, Popen, run

import octoprint.plugin
import octoprint.util
import requests
from flask import jsonify, make_response, request
from octoprint.events import Events
from octoprint.server.util.flask import restricted_access
from octoprint.util import RepeatedTimer
from RPi import GPIO
from smbus2 import SMBus
from werkzeug.exceptions import BadRequest

from .getPiTemp import PiTemp
from .ledstrip import LEDStrip

# Directory containing the sensor scripts run as subprocesses
SCRIPTS_DIR = Path(__file__).resolve().parent


# Function that returns Boolean output state of the GPIO inputs / outputs
def pin_state_boolean(pin, active_low):
    try:
        state = GPIO.input(pin)
        return (not state) if active_low else bool(state)
    except Exception:
        return "ERROR: Unable to read pin"


# Function that returns human-readable output state of the GPIO inputs / outputs
def pin_state_human(pin, active_low):
    pin_state = pin_state_boolean(pin, active_low)
    if pin_state is True:
        return " ON "
    if pin_state is False:
        return " OFF "
    return pin_state


# Translates the Pull-Up/Pull-Down GPIO resistor setting to active-low/active-high boolean
def check_input_active_low(input_pull_resistor):
    # input_pull_up
    # input_pull_down
    return input_pull_resistor == "input_pull_up"


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
    waiting_temperature = []
    rpi_outputs_not_changed = []
    notifications = []
    pwm_instances = []
    event_queue = []
    temp_hum_control_status = []
    temperature_sensor_data = []
    last_filament_end_detected = []
    print_complete = False
    development_mode = False
    dummy_value = 30.0
    dummy_delta = 0.5

    def __init__(self):
        # mqtt helper
        self.mqtt_publish = lambda *args, **kwargs: None
        # hardcoded
        self.mqtt_root_topic = "octoprint/plugins/enclosure"
        self.mqtt_sensor_topic = self.mqtt_root_topic + "/" + "enclosure"
        self.mqtt_message = '{"temperature": 0, "humidity": 0}'

    def start_timer(self):
        """Start the timer that checks the enclosure temperature."""
        self._check_temp_timer = RepeatedTimer(10, self.check_enclosure_temp, None, None, True)
        self._check_temp_timer.start()

    @staticmethod
    def to_float(value):
        """Convert value to float.

        Args:
            value (any): Value to be converted.

        Returns:
            float: Converted value, or 0 if the conversion fails.

        """
        try:
            return float(value)
        except Exception:
            return 0

    @staticmethod
    def to_int(value):
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def is_hour(value):
        try:
            datetime.strptime(value, "%H:%M")
        except Exception:
            return False
        else:
            return True

    @staticmethod
    def create_date(value):
        temp_string = datetime.now().strftime("%m/%d/%Y") + " " + value
        return datetime.strptime(temp_string, "%m/%d/%Y %H:%M")

    @staticmethod
    def constrain(n, minn, maxn):
        return max(min(maxn, n), minn)

    @staticmethod
    def get_gcode_value(command_string, gcode):
        semicolon = command_string.find(";")
        if semicolon != -1:
            command_string = command_string[:semicolon]

        for command in command_string.split(" "):
            index = command.upper().find(gcode.upper())
            if index != -1:
                return command.replace(gcode, "")
        return -1

    # ~~ StartupPlugin mixin
    def on_after_startup(self):
        helpers = self._plugin_manager.get_helpers("mqtt", "mqtt_publish", "mqtt_subscribe", "mqtt_unsubscribe")

        if helpers:
            if "mqtt_publish" in helpers:
                self.mqtt_publish = helpers["mqtt_publish"]
        else:
            self._logger.info("mqtt helpers not found. mqtt functions won't work")

        self.pwm_instances = []
        self.event_queue = []
        self.rpi_outputs_not_changed = []
        self.rpi_outputs = self._settings.get(["rpi_outputs"])
        self.rpi_inputs = self._settings.get(["rpi_inputs"])
        self.notifications = self._settings.get(["notifications"])
        # Reset volatile temp_ctr_set_value to 0 on startup (it should not be persisted)
        for rpi_output in self.rpi_outputs:
            rpi_output["temp_ctr_set_value"] = 0
        self.generate_temp_hum_control_status()
        self.setup_gpio()
        self.configure_gpio()
        self.update_ui()
        self.start_outpus_with_server()
        self.handle_initial_gpio_control()
        self.start_timer()
        self.print_complete = False

    def get_settings_version(self):
        return 10

    def on_settings_migrate(self, target, current=None):
        self._logger.warning(
            "######### current settings version %s target settings version %s #########",
            current,
            target,
        )
        self._logger.info("#########        Current settings        #########")
        self._logger.info("rpi_outputs: %s", self.rpi_outputs)
        self._logger.info("rpi_inputs: %s", self.rpi_inputs)
        self._logger.info("#########        End Current Settings        #########")
        if current >= 4 and target == 10:
            self._logger.warning("######### migrating settings to v10 #########")
            old_outputs = self._settings.get(["rpi_outputs"])
            old_inputs = self._settings.get(["rpi_inputs"])
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
            self._settings.set(["rpi_outputs"], old_outputs)

            old_inputs = self._settings.get(["rpi_inputs"])
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
            self._settings.set(["rpi_inputs"], old_inputs)
        else:
            self._logger.warning("######### settings not compatible #########")
            self._settings.set(["rpi_outputs"], [])
            self._settings.set(["rpi_inputs"], [])
            self.rpi_inputs = self._settings.get(["rpi_inputs"])

    # ~~ Blueprintplugin mixin
    def is_blueprint_csrf_protected(self):
        return True

    @octoprint.plugin.BlueprintPlugin.route("/ReadPin/<int:identifier>", methods=["GET"])
    def read_single_pin(self, identifier):
        resp = []
        match_found = False
        for rpi_input in self.rpi_inputs:
            if identifier == self.to_int(rpi_input["gpio_pin"]):
                match_found = True
                configured_as = "Input"
                active_low = check_input_active_low(rpi_input["input_pull_resistor"])
                pin = self.to_int(rpi_input["gpio_pin"])
                val = pin_state_human(pin, active_low)
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
            if identifier == self.to_int(rpi_output["gpio_pin"]):
                match_found = True
                configured_as = "Output"
                active_low = check_input_active_low(rpi_output["active_low"])
                pin = self.to_int(rpi_output["gpio_pin"])
                if rpi_output["gpio_i2c_enabled"]:
                    b = self.gpio_i2c_input(rpi_output, active_low)
                    val = " ON " if b else " OFF "
                else:
                    val = pin_state_human(pin, active_low)
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
                val = GPIO.input(pin)
            except Exception:
                val = "GPIO pin not initialized."
            resp.append({"Configured_As": configured_as, "GPIO_Pin": pin, "Active_Low": active_low, "State": val})
        return jsonify(resp)

    @octoprint.plugin.BlueprintPlugin.route("/inputs", methods=["GET"])
    def get_inputs(self):
        inputs = []
        for rpi_input in self.rpi_inputs:
            index = self.to_int(rpi_input["index_id"])
            label = rpi_input["label"]
            active_low = check_input_active_low(rpi_input["input_pull_resistor"])
            pin = self.to_int(rpi_input["gpio_pin"])
            val = pin_state_human(pin, active_low)
            inputs.append({"index_id": index, "label": label, "GPIO_Pin": pin, "State": val})
        return jsonify(inputs)

    @octoprint.plugin.BlueprintPlugin.route("/inputs/<int:identifier>", methods=["GET"])
    def get_input_status(self, identifier):
        for rpi_input in self.rpi_inputs:
            if identifier == self.to_int(rpi_input["index_id"]):
                return jsonify(rpi_input)
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

        for temp_hum_control in [item for item in self.rpi_outputs if item["index_id"] == identifier]:
            temp_hum_control["temp_ctr_set_value"] = set_value

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

        for sensor in self.rpi_inputs:
            if identifier == self.to_int(sensor["index_id"]):
                sensor["filament_sensor_enabled"] = value
                self._logger.info("Setting filament sensor for input %s to : %s", str(identifier), value)
        self._settings.set(["rpi_inputs"], self.rpi_inputs)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/outputs", methods=["GET"])
    def get_outputs(self):
        outputs = []
        for rpi_output in self.rpi_outputs:
            if rpi_output["output_type"] == "regular":
                index = self.to_int(rpi_output["index_id"])
                label = rpi_output["label"]
                pin = self.to_int(rpi_output["gpio_pin"])
                active_low = rpi_output["active_low"]
                if rpi_output["gpio_i2c_enabled"]:
                    b = self.gpio_i2c_input(rpi_output, active_low)
                    val = " ON " if b else " OFF "
                else:
                    val = pin_state_human(pin, active_low)
                outputs.append({"index_id": index, "label": label, "GPIO_Pin": pin, "State": val})
        return jsonify(outputs)

    @octoprint.plugin.BlueprintPlugin.route("/outputs/<int:identifier>", methods=["GET"])
    def get_output_status(self, identifier):
        for rpi_output in self.rpi_outputs:
            if identifier == self.to_int(rpi_output["index_id"]):
                out = copy.deepcopy(rpi_output)
                pin = self.to_int(rpi_output["gpio_pin"])
                if rpi_output["gpio_i2c_enabled"]:
                    out["current_value"] = self.gpio_i2c_input(rpi_output, rpi_output["active_low"])
                else:
                    out["current_value"] = pin_state_boolean(pin, rpi_output["active_low"])
                return jsonify(out)
        return make_response("", 404)

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
            if identifier == self.to_int(rpi_output["index_id"]):
                val = (not value) if rpi_output["active_low"] else value
                if rpi_output["gpio_i2c_enabled"]:
                    self.gpio_i2c_write(rpi_output, val)
                else:
                    self.write_gpio(self.to_int(rpi_output["gpio_pin"]), val)
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
            if identifier == self.to_int(output["index_id"]):
                output["auto_startup"] = value
                self._logger.info("Setting auto startup for output %s to : %s", str(identifier), value)
        self._settings.set(["rpi_outputs"], self.rpi_outputs)
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
            if identifier == self.to_int(output["index_id"]):
                output["auto_shutdown"] = value
                self._logger.info("Setting auto shutdown for output %s to : %s", str(identifier), value)
        self._settings.set(["rpi_outputs"], self.rpi_outputs)
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

        set_value = self.to_int(data["duty_cycle"])
        for rpi_output in [item for item in self.rpi_outputs if item["index_id"] == identifier]:
            rpi_output["duty_cycle"] = set_value
            rpi_output["new_duty_cycle"] = ""
            gpio = self.to_int(rpi_output["gpio_pin"])
            self.write_pwm(gpio, set_value)
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
            if identifier == self.to_int(rpi_output["index_id"]):
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

        red = data["red"]
        green = data["green"]
        blue = data["blue"]

        for rpi_output in self.rpi_outputs:
            if identifier == self.to_int(rpi_output["index_id"]):
                led_count = rpi_output["neopixel_count"]
                led_brightness = rpi_output["neopixel_brightness"]
                address = rpi_output["microcontroller_address"]

                neopixel_dirrect = rpi_output["output_type"] == "neopixel_direct"

                self.send_neopixel_command(
                    self.to_int(rpi_output["gpio_pin"]),
                    led_count,
                    led_brightness,
                    red,
                    green,
                    blue,
                    address,
                    neopixel_dirrect,
                    identifier,
                )

        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/clear-gpio", methods=["POST"])
    @restricted_access
    def clear_gpio_mode(self):
        GPIO.cleanup()
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/update", methods=["POST"])
    @restricted_access
    def update_ui_requested(self):
        self.update_ui()
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/shell/<int:identifier>", methods=["POST"])
    @restricted_access
    def send_shell_command(self, identifier):
        rpi_output = [r_out for r_out in self.rpi_outputs if self.to_int(r_out["index_id"]) == identifier].pop()

        command = rpi_output["shell_script"]
        self.shell_command(command)
        return make_response("", 204)

    @octoprint.plugin.BlueprintPlugin.route("/gcode/<int:identifier>", methods=["POST"])
    @restricted_access
    def requested_gcode_command(self, identifier):
        rpi_output = [r_out for r_out in self.rpi_outputs if self.to_int(r_out["index_id"]) == identifier].pop()
        self.send_gcode_command(rpi_output["gcode"])
        return make_response("", 204)

    # GPIO over i2c

    def gpio_i2c_input(self, output, active_low=None):
        state = False
        try:
            i2cbus = self.to_int(output["gpio_i2c_bus"])
            i2caddr = self.to_int(output["gpio_i2c_address"])
            i2creg = self.to_int(output["gpio_i2c_register_status"])
            data_on = self.to_int(output["gpio_i2c_data_on"])

            with SMBus(i2cbus) as bus:
                data = bus.read_i2c_block_data(i2caddr, i2creg, 1)
                if data[0] == data_on:
                    state = True

            self._logger.debug(
                "gpio_i2c_input(i2cbus=%s, i2caddr=%s, i2creg=%s, data_on=%s) data == %s",
                i2cbus,
                i2caddr,
                i2creg,
                data_on,
                data,
            )

            if active_low is None and state:
                return state

        except Exception:
            self._logger.exception(
                "Error reading on i2c address %s, reg %s",
                output["gpio_i2c_address"],
                output["gpio_i2c_register_status"],
            )

        return (not state) if active_low else state

    def gpio_i2c_write(self, output, state, queue_id=None):
        try:
            i2cbus = self.to_int(output["gpio_i2c_bus"])
            i2caddr = self.to_int(output["gpio_i2c_address"])
            i2creg = self.to_int(output["gpio_i2c_register"])
            data_on = self.to_int(output["gpio_i2c_data_on"])
            data_off = self.to_int(output["gpio_i2c_data_off"])

            with SMBus(i2cbus) as bus:
                data = []
                if state:
                    data.append(data_on)
                else:
                    data.append(data_off)

                bus.write_i2c_block_data(i2caddr, i2creg, data)

            if queue_id is not None:
                self._logger.debug("Running scheduled queue id %s", queue_id)
            self._logger.debug(
                "Writing on GPIO (i2c): %s/%s value %s",
                output["gpio_i2c_address"],
                output["gpio_i2c_register"],
                state,
            )
            self.update_ui()
            if queue_id is not None:
                self.stop_queue_item(queue_id)

        except Exception:
            self._logger.exception(
                "Error writing on i2c address %s, reg %s",
                output["gpio_i2c_address"],
                output["gpio_i2c_register"],
            )

    def send_neopixel_command(
        self,
        led_pin,
        led_count,
        led_brightness,
        red,
        green,
        blue,
        address,
        neopixel_dirrect,
        index_id,
        queue_id=None,
    ):
        """Send neopixel command.

        Args:
            led_pin (int): GPIO number.
            led_count (int): Number of LEDs.
            led_brightness (int): Brightness from 0 to 255.
            red (int): Red value from 0 to 255.
            green (int): Green value from 0 to 255.
            blue (int): Blue value from 0 to 255.
            address (int): I2C address of the microcontroller.
            neopixel_dirrect (bool): True to drive the LEDs from the Pi GPIO, False to use the I2C microcontroller.
            index_id (int): Index of the output whose color is being set.
            queue_id (str, optional): Scheduled queue item to remove after sending the command.

        """
        try:
            for rpi_output in self.rpi_outputs:
                if self.to_int(index_id) == self.to_int(rpi_output["index_id"]):
                    rpi_output["neopixel_color"] = f"rgb({red},{green},{blue})"

            if address == "":
                address = 0

            if neopixel_dirrect:
                # rpi_ws281x requires root, so neopixel_direct.py runs with the system python
                script = str(SCRIPTS_DIR / "neopixel_direct.py")
                cmd = ["python3", script]
            else:
                script = str(SCRIPTS_DIR / "neopixel_indirect.py")
                cmd = [sys.executable, script]

            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")

            cmd += [str(led_pin), str(led_count), str(led_brightness), str(red), str(green), str(blue)]

            if neopixel_dirrect:
                dma = self._settings.get(["neopixel_dma"]) or 10
                cmd.append(str(dma))
            else:
                cmd.append(str(address))

                if queue_id is not None:
                    self._logger.debug("running scheduled queue id %s", queue_id)
                self._logger.debug("Sending neopixel cmd: %s", cmd)
            Popen(cmd)
            if queue_id is not None:
                self.stop_queue_item(queue_id)
        except Exception:
            self._logger.exception("Error sending neopixel command for output %s", index_id)

    def check_enclosure_temp(self):
        try:
            sensor_data = []
            for sensor in list(filter(lambda item: item["input_type"] == "temperature_sensor", self.rpi_inputs)):
                temp, hum, airquality = self.get_sensor_data(sensor)
                if self._settings.get(["debug_temperature_log"]) is True:
                    self._logger.debug(
                        "Sensor %s Temperature: %s humidity %s Airquality %s",
                        sensor["label"],
                        temp,
                        hum,
                        airquality,
                    )
                if temp is not None and hum is not None and airquality is not None:
                    sensor["temp_sensor_temp"] = temp
                    sensor["temp_sensor_humidity"] = hum
                    sensor_data.append(
                        {
                            "index_id": sensor["index_id"],
                            "temperature": temp,
                            "humidity": hum,
                            "airquality": airquality,
                        },
                    )
                    self.temperature_sensor_data = sensor_data
                    self.handle_temp_hum_control()
                    self.handle_temperature_events()
                    self.handle_pwm_linked_temperature()
                    self.update_ui()
                    self.mqtt_sensor_topic = self.mqtt_root_topic + "/" + sensor["label"]
                    self.mqtt_message = {"temperature": temp, "humidity": hum}
                    self.mqtt_publish(self.mqtt_sensor_topic, self.mqtt_message)
        except Exception:
            self._logger.exception("Error checking enclosure temperature")

    def toggle_output(self, output_index, first_run=False):
        for output in [item for item in self.rpi_outputs if item["index_id"] == output_index]:
            gpio_pin = self.to_int(output["gpio_pin"])
            index_id = self.to_int(output["index_id"])

            if output["output_type"] == "regular":
                if output["gpio_i2c_enabled"]:
                    current_value = self.gpio_i2c_input(output)
                elif first_run:
                    current_value = False
                else:
                    current_value = (not GPIO.input(gpio_pin)) if output["active_low"] else GPIO.input(gpio_pin)

                if current_value:
                    time_delay = self.to_int(output["toggle_timer_off"])
                else:
                    time_delay = self.to_int(output["toggle_timer_on"])

                if not self.print_complete:
                    if output["gpio_i2c_enabled"]:
                        self.gpio_i2c_write(output, not current_value)
                    else:
                        self.write_gpio(gpio_pin, not current_value)
                    thread = threading.Timer(time_delay, self.toggle_output, args=[index_id])
                    thread.start()
                else:
                    off_value = bool(output["active_low"])
                    if output["gpio_i2c_enabled"]:
                        self.gpio_i2c_write(output, off_value)
                    else:
                        self.write_gpio(gpio_pin, off_value)
                self.update_ui_outputs()
                return

            if output["output_type"] == "pwm":
                for pwm in self.pwm_instances:
                    if gpio_pin in pwm:
                        if first_run:
                            current_pwm_value = 0
                        elif "duty_cycle" in pwm:
                            current_pwm_value = pwm["duty_cycle"]
                            current_pwm_value = self.to_int(current_pwm_value)
                        else:
                            current_pwm_value = 0

                        if current_pwm_value != 0:
                            time_delay = self.to_int(output["toggle_timer_off"])
                            write_value = 0
                        else:
                            time_delay = self.to_int(output["toggle_timer_on"])
                            write_value = self.to_int(output["default_duty_cycle"])

                        if not self.print_complete:
                            self.write_pwm(gpio_pin, write_value)
                            thread = threading.Timer(time_delay, self.toggle_output, args=[index_id])
                            thread.start()
                        else:
                            self.write_pwm(self.to_int(output["gpio_pin"]), 0)
                        self.update_ui_outputs()
                        return

    def update_ui(self):
        self.update_ui_outputs()
        self.update_ui_current_temperature()
        self.update_ui_set_temperature()
        self.update_ui_inputs()

    def update_ui_current_temperature(self):
        self._plugin_manager.send_plugin_message(self._identifier, {"sensor_data": self.temperature_sensor_data})

    def update_ui_set_temperature(self):
        result = []
        for temp_crt_output in list(filter(lambda item: item["output_type"] == "temp_hum_control", self.rpi_outputs)):
            set_temperature = self.to_float(temp_crt_output["temp_ctr_set_value"])
            result.append({"index_id": temp_crt_output["index_id"], "set_temperature": set_temperature})
            result.append(set_temperature)
        self._plugin_manager.send_plugin_message(self._identifier, {"set_temperature": result})

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
                index = self.to_int(output["index_id"])
                pin = self.to_int(output["gpio_pin"])
                startup = output["auto_startup"]
                shutdown = output["auto_shutdown"]

                if output["output_type"] == "regular":
                    if output["gpio_i2c_enabled"]:
                        val = self.gpio_i2c_input(output)
                    else:
                        val = GPIO.input(pin) if not output["active_low"] else (not GPIO.input(pin))
                    regular_status.append(
                        {"index_id": index, "status": val, "auto_startup": startup, "auto_shutdown": shutdown},
                    )
                if output["output_type"] == "temp_hum_control":
                    if output["gpio_i2c_enabled"]:
                        val = self.gpio_i2c_input(output)
                    else:
                        val = GPIO.input(pin) if not output["active_low"] else (not GPIO.input(pin))
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
                    for pwm in self.pwm_instances:
                        if pin in pwm:
                            if "duty_cycle" in pwm:
                                pwm_val = pwm["duty_cycle"]
                                val = self.to_int(pwm_val)
                            else:
                                val = 0
                            pwm_status.append(
                                {
                                    "index_id": index,
                                    "pwm_value": val,
                                    "auto_startup": startup,
                                    "auto_shutdown": shutdown,
                                },
                            )
            self._plugin_manager.send_plugin_message(
                self._identifier,
                {
                    "rpi_output_regular": regular_status,
                    "rpi_output_pwm": pwm_status,
                    "rpi_output_neopixel": neopixel_status,
                    "rpi_output_ledstrip": ledstrip_status,
                    "rpi_output_temp_hum_ctrl": temp_control_status,
                },
            )
        except Exception:
            self._logger.exception("Error sending outputs status to the UI")

    def update_ui_inputs(self):
        try:
            sensor_status = []
            for sensor in self.rpi_inputs:
                if (
                    sensor["input_type"] == "gpio"
                    and sensor["action_type"] == "printer_control"
                    and sensor["printer_action"] == "filament"
                ):
                    index = self.to_int(sensor["index_id"])
                    value = sensor["filament_sensor_enabled"]
                    sensor_status.append({"index_id": index, "filament_sensor_enabled": value})
            self._plugin_manager.send_plugin_message(self._identifier, {"filament_sensor_status": sensor_status})
        except Exception:
            self._logger.exception("Error sending input status to the UI")

    def get_sensor_data(self, sensor):
        try:
            if self.development_mode:
                temp, hum, airquality = self.read_dummy_temp()
            elif sensor["temp_sensor_type"] in ["11", "22", "2302"]:
                temp, hum = self.read_dht_temp(sensor["temp_sensor_type"], sensor["gpio_pin"])
                airquality = 0
            elif sensor["temp_sensor_type"] == "20":
                temp, hum = self.read_dht20_temp(sensor["temp_sensor_address"], sensor["temp_sensor_i2cbus"])
                airquality = 0
            elif sensor["temp_sensor_type"] == "18b20":
                temp = self.read_18b20_temp(sensor["ds18b20_serial"])
                hum = 0
                airquality = 0
            elif sensor["temp_sensor_type"] == "bme280":
                temp, hum = self.read_bme280_temp(sensor["temp_sensor_address"])
                airquality = 0
            elif sensor["temp_sensor_type"] == "bme680":
                temp, hum, airquality = self.read_bme680_temp(sensor["temp_sensor_address"])
            elif sensor["temp_sensor_type"] == "am2320":
                temp, hum = self.read_am2320_temp()  # sensor has fixed address
                airquality = 0
            elif sensor["temp_sensor_type"] == "aht10":
                temp, hum = self.read_aht10_temp(sensor["temp_sensor_address"], sensor["temp_sensor_i2cbus"])
                airquality = 0
            elif sensor["temp_sensor_type"] == "rpi":
                temp = self.read_rpi_temp()  # rpi CPU Temp
                hum = 0
                airquality = 0
            elif sensor["temp_sensor_type"] == "si7021":
                temp, hum = self.read_si7021_temp(sensor["temp_sensor_address"], sensor["temp_sensor_i2cbus"])
                airquality = 0
            elif sensor["temp_sensor_type"] == "tmp102":
                temp = self.read_tmp102_temp(sensor["temp_sensor_address"])
                hum = 0
                airquality = 0
            elif sensor["temp_sensor_type"] == "max31855":
                temp = self.read_max31855_temp(sensor["temp_sensor_address"])
                hum = 0
                airquality = 0
            elif sensor["temp_sensor_type"] == "mcp9808":
                temp = self.read_mcp_temp(sensor["temp_sensor_address"], sensor["temp_sensor_i2cbus"])
                hum = 0
                airquality = 0
            elif sensor["temp_sensor_type"] == "temp_raw_i2c":
                temp, hum = self.read_raw_i2c_temp(sensor)
                airquality = 0
            elif sensor["temp_sensor_type"] == "hum_raw_i2c":
                hum, temp = self.read_raw_i2c_temp(sensor)
                airquality = 0
            else:
                self._logger.info("temp_sensor_type no match")
                temp = None
                hum = None
                airquality = 0
        except Exception:
            self._logger.exception("Error reading sensor %s", sensor["label"])
        else:
            if temp != -1 and hum != -1 and airquality != -1:
                temp = (
                    round(self.to_float(temp), 1)
                    if not sensor["use_fahrenheit"]
                    else round(self.to_float(temp) * 1.8 + 32, 1)
                )
                hum = round(self.to_float(hum), 1)
                airquality = round(self.to_float(airquality), 1)
                return temp, hum, airquality
            return None, None, None

    def handle_temperature_events(self):
        for temperature_alarm in [item for item in self.rpi_outputs if item["output_type"] == "temperature_alarm"]:
            set_temperature = self.to_float(temperature_alarm["alarm_set_temp"])
            if int(set_temperature) == 0:
                continue
            linked_data = [
                item
                for item in self.temperature_sensor_data
                if item["index_id"] == temperature_alarm["linked_temp_sensor"]
            ].pop()
            sensor_temperature = self.to_float(linked_data["temperature"])
            if set_temperature < sensor_temperature:
                for rpi_controlled_output in self.rpi_outputs:
                    if self.to_int(temperature_alarm["controlled_io"]) == self.to_int(
                        rpi_controlled_output["index_id"],
                    ):
                        if rpi_controlled_output["gpio_i2c_enabled"]:
                            val = temperature_alarm["controlled_io_set_value"] != "low"
                            self.gpio_i2c_write(rpi_controlled_output, val)
                        else:
                            val = GPIO.LOW if temperature_alarm["controlled_io_set_value"] == "low" else GPIO.HIGH
                            self.write_gpio(self.to_int(rpi_controlled_output["gpio_pin"]), val)
                        for notification in self.notifications:
                            if notification["temperatureAction"]:
                                msg = (
                                    "Temperature action: enclosure temperature exceed "
                                    + temperature_alarm["alarm_set_temp"]
                                )
                                self.send_notification(msg)

    def read_dummy_temp(self):
        current_value = self.dummy_value
        if current_value > 40 or current_value < 30:
            self.dummy_delta = -self.dummy_delta

        return_value = current_value + self.dummy_delta

        self.dummy_value = return_value

        return return_value, return_value, return_value

    def read_raw_i2c_temp(self, sensor):
        try:
            i2cbus = self.to_int(sensor["temp_i2c_bus"])
            i2caddr = self.to_int(sensor["temp_i2c_address"])
            i2creg = self.to_int(sensor["temp_i2c_register"])

            with SMBus(i2cbus) as bus:
                data = bus.read_i2c_block_data(i2caddr, i2creg, 8)
                fval1 = struct.unpack("f", bytearray(data[0:4]))[0]
                if math.isnan(fval1):
                    fval1 = 0
                fval2 = struct.unpack("f", bytearray(data[4:8]))[0]
                if math.isnan(fval2):
                    fval2 = 0

                self._logger.debug(
                    "read_raw_i2c_temp(i2cbus=%s, i2caddr=%s, i2creg=%s) data == %s (%s, %s)",
                    i2cbus,
                    i2caddr,
                    i2creg,
                    data,
                    fval1,
                    fval2,
                )

                return (fval1, fval2)

        except Exception:
            self._logger.exception("Error reading on i2c address %s, reg %s", i2caddr, i2creg)
            return str(-1)

    def read_mcp_temp(self, address, i2cbus):
        try:
            script = str(SCRIPTS_DIR / "mcp9808.py")
            args = [sys.executable, script, str(i2cbus), str(address)]
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature MCP9808 cmd: %s", " ".join(args))
            proc = Popen(args, stdout=PIPE)
            stdout, _ = proc.communicate()
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("MCP9808 result: %s", stdout)
            return self.to_float(stdout.decode("utf-8").strip())
        except Exception:
            self._logger.exception("Failed to read MCP9808 sensor")
            return 0

    def read_dht_temp(self, sensor, pin):
        try:
            script = str(SCRIPTS_DIR / "getDHTTemp.py")
            cmd = [sys.executable, script, str(sensor), str(pin)]
            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature dht cmd: %s", cmd)
            stdout = (Popen(cmd, stdout=PIPE).stdout).read()
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Dht result: %s", stdout)
            temp, hum = stdout.decode("utf-8").split("|")
            return (self.to_float(temp.strip()), self.to_float(hum.strip()))
        except Exception:
            self._logger.exception("Failed to read DHT sensor, try disabling Use SUDO in the advanced options")
            return (0, 0)

    def read_dht20_temp(self, address, i2cbus):
        try:
            script = str(SCRIPTS_DIR / "DHT20.py")
            cmd = [sys.executable, script, str(address), str(i2cbus)]
            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature DHT20 cmd: %s", cmd)
            stdout = (Popen(cmd, stdout=PIPE).stdout).read()
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("DHT20 result: %s", stdout)
            temp, hum = stdout.decode("utf-8").split("|")
            return (self.to_float(temp.strip()), self.to_float(hum.strip()))
        except Exception:
            self._logger.exception("Failed to read DHT20 sensor, try disabling Use SUDO in the advanced options")
            return (0, 0)

    def read_bme280_temp(self, address):
        try:
            script = str(SCRIPTS_DIR / "BME280.py")
            cmd = [sys.executable, script, str(address)]
            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature BME280 cmd: %s", cmd)

            stdout = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
            output, errors = stdout.communicate()

            if self._settings.get(["debug_temperature_log"]) is True:
                if len(errors) > 0:
                    self._logger.error("BME280 error: %s", errors)
                else:
                    self._logger.debug("BME280 result: %s", output)

            temp, hum = output.split("|")
            return (self.to_float(temp.strip()), self.to_float(hum.strip()))
        except Exception:
            self._logger.exception("Failed to read BME280 sensor, try disabling Use SUDO in the advanced options")
            return (0, 0)

    def read_bme680_temp(self, address):
        try:
            script = str(SCRIPTS_DIR / "BME680.py")
            cmd = [sys.executable, script, str(address)]
            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature BME680 cmd: %s", cmd)

            stdout = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
            output, errors = stdout.communicate()

            if self._settings.get(["debug_temperature_log"]) is True:
                if len(errors) > 0:
                    self._logger.error("BME680 error: %s", errors)
                else:
                    self._logger.debug("BME680 result: %s", output)
            temp, hum, airq = output.split("|")
            return (self.to_float(temp.strip()), self.to_float(hum.strip()), self.to_float(airq.strip()))
        except Exception:
            self._logger.exception("Failed to read BME680 sensor, try disabling Use SUDO in the advanced options")
            return (0, 0, 0)

    def read_am2320_temp(self):
        try:
            script = str(SCRIPTS_DIR / "AM2320.py")
            cmd = [sys.executable, script]  # sensor has fixed address 0x5C
            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature AM2320 cmd: %s", cmd)
            stdout = (Popen(cmd, stdout=PIPE).stdout).read()
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("AM2320 result: %s", stdout)
            temp, hum = stdout.decode("utf-8").split("|")
            return (self.to_float(temp.strip()), self.to_float(hum.strip()))
        except Exception:
            self._logger.exception("Failed to read AM2320 sensor, try disabling Use SUDO in the advanced options")
            return (0, 0)

    def read_aht10_temp(self, address, i2cbus):
        try:
            script = str(SCRIPTS_DIR / "AHT10.py")
            cmd = [sys.executable, script, str(address), str(i2cbus)]
            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature AHT10 cmd: %s", cmd)
            stdout = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
            output, errors = stdout.communicate()
            if self._settings.get(["debug_temperature_log"]) is True:
                if len(errors) > 0:
                    self._logger.error("AHT10 error: %s", errors)
                else:
                    self._logger.debug("AHT10 result: %s", output)
            temp, hum = output.split("|")
            return (self.to_float(temp.strip()), self.to_float(hum.strip()))
        except Exception:
            self._logger.exception("Failed to read AHT10 sensor, try disabling Use SUDO in the advanced options")
            return (0, 0)

    def read_rpi_temp(self):
        try:
            pitemp = PiTemp()
            temp = pitemp.get_temp()
        except Exception:
            self._logger.exception("Failed to read Raspberry Pi CPU temperature")
            return 0
        else:
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Pi CPU result: %s", temp)
            return temp

    def read_si7021_temp(self, address, i2cbus):
        try:
            script = str(SCRIPTS_DIR / "SI7021.py")
            cmd = [sys.executable, script, str(address), str(i2cbus)]
            if self._settings.get(["use_sudo"]):
                cmd.insert(0, "sudo")
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature SI7021 cmd: %s", cmd)
            stdout = (Popen(cmd, stdout=PIPE).stdout).read()
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("SI7021 result: %s", stdout)
            temp, hum = stdout.decode("utf-8").split("|")
            return (self.to_float(temp.strip()), self.to_float(hum.strip()))
        except Exception:
            self._logger.exception("Failed to read SI7021 sensor, try disabling Use SUDO in the advanced options")
            return (0, 0)

    def read_18b20_temp(self, serial_number):
        with contextlib.suppress(OSError):
            run(["modprobe", "w1-gpio"], check=False)
            run(["modprobe", "w1-therm"], check=False)

        lines = self.read_raw_18b20_temp(serial_number)
        while lines[0].strip()[-3:] != "YES":
            time.sleep(0.2)
            lines = self.read_raw_18b20_temp(serial_number)
        equals_pos = lines[1].find("t=")
        if equals_pos != -1:
            temp_string = lines[1][equals_pos + 2 :]
            temp_c = float(temp_string) / 1000.0
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("DS18B20 result: %s", temp_c)
            return f"{temp_c:0.1f}"
        return 0

    def read_raw_18b20_temp(self, serial_number):
        base_dir = Path("/sys/bus/w1/devices/")
        device_folder = next(base_dir.glob(str(serial_number) + "*"))
        device_file = device_folder / "w1_slave"
        with device_file.open() as device_file_result:
            return device_file_result.readlines()

    def read_tmp102_temp(self, address):
        try:
            script = str(SCRIPTS_DIR / "tmp102.py")
            args = [sys.executable, script, str(address)]
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature TMP102 cmd: %s", " ".join(args))
            proc = Popen(args, stdout=PIPE)
            stdout, _ = proc.communicate()
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("TMP102 result: %s", stdout)
            return self.to_float(stdout.decode("utf-8").strip())
        except Exception:
            self._logger.exception("Failed to read TMP102 sensor")
            return 0

    def read_max31855_temp(self, address):
        try:
            script = str(SCRIPTS_DIR / "max31855.py")
            args = [sys.executable, script, str(address)]
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("Temperature MAX31855 cmd: %s", " ".join(args))
            proc = Popen(args, stdout=PIPE)
            stdout, _ = proc.communicate()
            if self._settings.get(["debug_temperature_log"]) is True:
                self._logger.debug("MAX31855 result: %s", stdout)
            return self.to_float(stdout.decode("utf-8").strip())
        except Exception:
            self._logger.exception("Failed to read MAX31855 sensor")
            return 0

    def handle_pwm_linked_temperature(self):
        try:
            for pwm_output in list(
                filter(lambda item: item["output_type"] == "pwm" and item["pwm_temperature_linked"], self.rpi_outputs),
            ):
                gpio_pin = self.to_int(pwm_output["gpio_pin"])
                if self._printer.is_printing():
                    index_id = self.to_int(pwm_output["index_id"])
                    linked_id = self.to_int(pwm_output["linked_temp_sensor"])
                    linked_data = self.get_linked_temp_sensor_data(linked_id)
                    current_temp = self.to_float(linked_data["temperature"])

                    duty_a = self.to_float(pwm_output["duty_a"])
                    duty_b = self.to_float(pwm_output["duty_b"])
                    temp_a = self.to_float(pwm_output["temperature_a"])
                    temp_b = self.to_float(pwm_output["temperature_b"])

                    try:
                        calculated_duty = ((current_temp - temp_a) * (duty_b - duty_a) / (temp_b - temp_a)) + duty_a

                        if current_temp < temp_a:
                            calculated_duty = 0
                    except Exception:
                        calculated_duty = 0

                    self._logger.debug("Calculated duty for PWM %s is %s", index_id, calculated_duty)
                elif self.print_complete:
                    calculated_duty = self.to_int(pwm_output["duty_cycle"])
                else:
                    calculated_duty = 0

                self.write_pwm(gpio_pin, self.constrain(calculated_duty, 0, 100))

        except Exception:
            self._logger.exception("Error handling temperature linked PWM outputs")

    def get_linked_temp_sensor_data(self, linked_id):
        try:
            return [data for data in self.temperature_sensor_data if data["index_id"] == linked_id].pop()
        except Exception:
            self._logger.warning("No linked temperature sensor found for %s", linked_id)
            return None

    def handle_temp_hum_control(self):
        try:
            for temp_hum_control in list(
                filter(lambda item: item["output_type"] == "temp_hum_control", self.rpi_outputs),
            ):
                set_temperature = self.to_float(temp_hum_control["temp_ctr_set_value"])
                temp_deadband = self.to_float(temp_hum_control["temp_ctr_deadband"])
                max_temp = self.to_float(temp_hum_control["temp_ctr_max_temp"])

                linked_id = temp_hum_control["linked_temp_sensor"]

                previous_status = list(
                    filter(lambda item: item["index_id"] == temp_hum_control["index_id"], self.temp_hum_control_status),
                ).pop()["status"]

                if set_temperature == 0:
                    current_status = False
                else:
                    linked_data = self.get_linked_temp_sensor_data(linked_id)

                    control_type = str(temp_hum_control["temp_ctr_type"])

                    if control_type == "dehumidifier":
                        current_value = self.to_float(linked_data["humidity"])
                        temp_deadband = 0
                    else:
                        current_value = self.to_float(linked_data["temperature"])

                    if control_type in {"cooler", "dehumidifier"}:
                        if current_value <= set_temperature and current_value >= (set_temperature - temp_deadband):
                            current_status = previous_status
                        elif current_value < set_temperature:
                            current_status = False
                        else:
                            current_status = True
                    elif current_value <= set_temperature and current_value >= (set_temperature - temp_deadband):
                        current_status = previous_status
                    elif current_value > set_temperature:
                        current_status = False
                    else:
                        current_status = True

                    if control_type == "heater" and max_temp > 0.0 and max_temp < current_value:
                        self._logger.debug(
                            "Maximum temperature reached for temperature control %s",
                            temp_hum_control["index_id"],
                        )
                        temp_hum_control["temp_ctr_set_value"] = 0
                        current_status = False

                if current_status != previous_status:
                    if current_status:
                        self._logger.info("Turning gpio to control temperature on.")
                        val = not temp_hum_control["active_low"]
                        if temp_hum_control["gpio_i2c_enabled"]:
                            self.gpio_i2c_write(temp_hum_control, val)
                        else:
                            self.write_gpio(self.to_int(temp_hum_control["gpio_pin"]), val)
                    else:
                        index_id = temp_hum_control["index_id"]
                        if index_id in self.waiting_temperature:
                            self.waiting_temperature.remove(index_id)

                        if not self.waiting_temperature and self._printer.is_paused():
                            self._printer.resume_print()

                        self._logger.info("Turning gpio to control temperature off.")
                        val = bool(temp_hum_control["active_low"])
                        if temp_hum_control["gpio_i2c_enabled"]:
                            self.gpio_i2c_write(temp_hum_control, val)
                        else:
                            self.write_gpio(self.to_int(temp_hum_control["gpio_pin"]), val)
                    for control_status in self.temp_hum_control_status:
                        if control_status["index_id"] == temp_hum_control["index_id"]:
                            control_status["status"] = current_status
        except Exception:
            self._logger.exception("Error handling temperature/humidity control")

    def setup_gpio(self):
        try:
            current_mode = GPIO.getmode()
            set_mode = GPIO.BOARD if self._settings.get(["use_board_pin_number"]) else GPIO.BCM
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
                    GPIO.setmode(set_mode)
                    tempstr = "BOARD" if set_mode == GPIO.BOARD else "BCM"
                    self._logger.info("Setting GPIO mode to %s", tempstr)
            elif current_mode != set_mode:
                GPIO.setmode(current_mode)
                tempstr = "BOARD" if current_mode == GPIO.BOARD else "BCM"
                self._settings.set(["use_board_pin_number"], current_mode == GPIO.BOARD)
                warn_msg = (
                    "GPIO mode was configured before, GPIO mode will be forced to use: "
                    + tempstr
                    + " as pin numbers. Please update GPIO accordingly!"
                )
                self._logger.info(warn_msg)
                self._plugin_manager.send_plugin_message(
                    self._identifier,
                    {"is_msg": True, "msg": warn_msg, "msg_type": "error"},
                )
            GPIO.setwarnings(False)
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
                gpio_pin = self.to_int(gpio_out["gpio_pin"])
                if gpio_pin not in self.rpi_outputs_not_changed:
                    GPIO.cleanup(gpio_pin)

            for gpio_in in list(filter(lambda item: item["input_type"] == "gpio", self.rpi_inputs)):
                with contextlib.suppress(Exception):
                    GPIO.remove_event_detect(self.to_int(gpio_in["gpio_pin"]))
                GPIO.cleanup(self.to_int(gpio_in["gpio_pin"]))
        except Exception:
            self._logger.exception("Error clearing GPIO")

    def clear_channel(self, channel):
        try:
            GPIO.cleanup(self.to_int(channel))
            self._logger.debug("Clearing channel %s", channel)
        except Exception:
            self._logger.exception("Error clearing channel %s", channel)

    def generate_temp_hum_control_status(self):
        self.temp_hum_control_status = [
            {"index_id": temp_hum_control["index_id"], "status": False}
            for temp_hum_control in self.rpi_outputs
            if temp_hum_control["output_type"] == "temp_hum_control"
        ]

    def configure_gpio(self):
        try:
            for gpio_out in list(
                filter(
                    lambda item: (
                        (item["output_type"] == "regular" or item["output_type"] == "temp_hum_control")
                        and not item["gpio_i2c_enabled"]
                    ),
                    self.rpi_outputs,
                ),
            ):
                initial_value = GPIO.HIGH if gpio_out["active_low"] else GPIO.LOW
                pin = self.to_int(gpio_out["gpio_pin"])
                if pin not in self.rpi_outputs_not_changed:
                    self._logger.info("Setting GPIO pin %s as OUTPUT with initial value: %s", pin, initial_value)
                    GPIO.setup(pin, GPIO.OUT, initial=initial_value)
            for gpio_out_pwm in list(filter(lambda item: item["output_type"] == "pwm", self.rpi_outputs)):
                pin = self.to_int(gpio_out_pwm["gpio_pin"])
                self._logger.info("Setting GPIO pin %s as PWM", pin)

                # Stop and clear any other pwm instances on that pin
                pwm_instances_to_remove = []
                for pwm_instance in self.pwm_instances:
                    if pin in pwm_instance:
                        pwm_instance[pin].stop()
                        pwm_instances_to_remove.append(pwm_instance)
                for pwm_instance in pwm_instances_to_remove:
                    self.pwm_instances.remove(pwm_instance)

                # Clear the pin
                self.clear_channel(pin)

                # Setup new pwm on that pin
                GPIO.setup(pin, GPIO.OUT)
                pwm_instance = GPIO.PWM(pin, self.to_int(gpio_out_pwm["pwm_frequency"]))

                # Start the pwm
                self._logger.info("starting PWM on pin %s", pin)
                pwm_instance.start(self.to_int(gpio_out_pwm["default_duty_cycle"]))

                # Add the pwm to pwm_instances list
                self.pwm_instances.append({pin: pwm_instance})
            for gpio_out_neopixel in list(
                filter(lambda item: item["output_type"] == "neopixel_direct", self.rpi_outputs),
            ):
                pin = self.to_int(gpio_out_neopixel["gpio_pin"])
                self.clear_channel(pin)

            for rpi_input in list(filter(lambda item: item["input_type"] == "gpio", self.rpi_inputs)):
                gpio_pin = self.to_int(rpi_input["gpio_pin"])
                pull_resistor = GPIO.PUD_UP if rpi_input["input_pull_resistor"] == "input_pull_up" else GPIO.PUD_DOWN
                GPIO.setup(gpio_pin, GPIO.IN, pull_resistor)
                edge = GPIO.RISING if rpi_input["edge"] == "rise" else GPIO.FALLING

                inputs_same_gpio = [r_inp for r_inp in self.rpi_inputs if self.to_int(r_inp["gpio_pin"]) == gpio_pin]

                if len(inputs_same_gpio) > 1:
                    GPIO.remove_event_detect(gpio_pin)
                    for other_input in inputs_same_gpio:
                        if other_input["edge"] != rpi_input["edge"]:
                            edge = GPIO.BOTH

                if rpi_input["action_type"] == "output_control":
                    self._logger.info("Adding GPIO event detect on pin %s with edge: %s", gpio_pin, edge)
                    GPIO.add_event_detect(gpio_pin, edge, callback=self.handle_gpio_control, bouncetime=200)
                if rpi_input["action_type"] == "printer_control" and rpi_input["printer_action"] != "filament":
                    GPIO.add_event_detect(gpio_pin, edge, callback=self.handle_printer_action, bouncetime=200)
                    self._logger.info("Adding PRINTER CONTROL event detect on pin %s with edge: %s", gpio_pin, edge)

            for rpi_input in list(filter(lambda item: item["input_type"] == "temperature_sensor", self.rpi_inputs)):
                gpio_pin = self.to_int(rpi_input["gpio_pin"])
                if rpi_input["input_pull_resistor"] == "input_pull_up":
                    pull_resistor = GPIO.PUD_UP
                elif rpi_input["input_pull_resistor"] == "input_pull_down":
                    pull_resistor = GPIO.PUD_DOWN
                else:
                    pull_resistor = GPIO.PUD_OFF
                GPIO.setup(gpio_pin, GPIO.IN, pull_up_down=pull_resistor)
        except Exception:
            self._logger.exception("Error configuring GPIO")

    def handle_filamment_detection(self, channel):
        try:
            for filament_sensor in list(
                filter(
                    lambda item: (
                        item["input_type"] == "gpio"
                        and item["action_type"] == "printer_control"
                        and item["printer_action"] == "filament"
                        and self.to_int(item["gpio_pin"]) == self.to_int(channel)
                    ),
                    self.rpi_inputs,
                ),
            ):
                if (filament_sensor["edge"] == "fall") ^ (
                    GPIO.input(self.to_int(filament_sensor["gpio_pin"]))
                ) and filament_sensor["filament_sensor_enabled"]:
                    last_detected_time = list(
                        filter(
                            lambda item: item["index_id"] == filament_sensor["index_id"],
                            self.last_filament_end_detected,
                        ),
                    ).pop()["time"]
                    time_now = time.time()
                    time_difference = self.to_int(time_now - last_detected_time)
                    time_out_value = self.to_int(filament_sensor["filament_sensor_timeout"])
                    if time_difference > time_out_value:
                        self._logger.info("Detected end of filament.")
                        for item in self.last_filament_end_detected:
                            if item["index_id"] == filament_sensor["index_id"]:
                                item["time"] = time_now
                        for line in self._settings.get(["filament_sensor_gcode"]).split("\n"):
                            if line:
                                self._printer.commands(line.strip())
                                self._logger.info("Sending GCODE command: %s", line.strip())
                                time.sleep(0.2)
                        for notification in self.notifications:
                            if notification["filamentChange"]:
                                msg = "Filament change action caused by sensor: " + str(filament_sensor["label"])
                                self.send_notification(msg)
                    else:
                        self._logger.info("Prevented end of filament detection, filament sensor timeout not elapsed.")
        except Exception:
            self._logger.exception("Error handling filament detection on channel %s", channel)

    def start_filament_detection(self):
        self.stop_filament_detection()
        try:
            for filament_sensor in list(
                filter(
                    lambda item: (
                        item["input_type"] == "gpio"
                        and item["action_type"] == "printer_control"
                        and item["printer_action"] == "filament"
                    ),
                    self.rpi_inputs,
                ),
            ):
                edge = GPIO.RISING if filament_sensor["edge"] == "rise" else GPIO.FALLING
                if GPIO.input(self.to_int(filament_sensor["gpio_pin"])) == (edge == GPIO.RISING):
                    self._printer.pause_print()
                    self._logger.info("Started printing with no filament.")
                else:
                    self.last_filament_end_detected.append({"index_id": filament_sensor["index_id"], "time": 0})
                    self._logger.info(
                        "Adding GPIO event detect on pin %s with edge: %s",
                        filament_sensor["gpio_pin"],
                        edge,
                    )
                    GPIO.add_event_detect(
                        self.to_int(filament_sensor["gpio_pin"]),
                        edge,
                        callback=self.handle_filamment_detection,
                        bouncetime=200,
                    )
        except Exception:
            self._logger.exception("Error starting filament detection")

    def stop_filament_detection(self):
        try:
            self.last_filament_end_detected = []
            for filament_sensor in list(
                filter(
                    lambda item: (
                        item["input_type"] == "gpio"
                        and item["action_type"] == "printer_control"
                        and item["printer_action"] == "filament"
                    ),
                    self.rpi_inputs,
                ),
            ):
                GPIO.remove_event_detect(self.to_int(filament_sensor["gpio_pin"]))
        except Exception:
            self._logger.exception("Error stopping filament detection")

    def cancel_all_events_on_queue(self):
        for task in self.event_queue:
            try:
                task["thread"].cancel()
            except Exception:
                self._logger.exception("Failed to stop task %s", task)

    def handle_initial_gpio_control(self):
        try:
            for rpi_input in list(
                filter(
                    lambda item: item["input_type"] == "gpio" and item["action_type"] == "output_control",
                    self.rpi_inputs,
                ),
            ):
                gpio_pin = self.to_int(rpi_input["gpio_pin"])
                controlled_io = self.to_int(rpi_input["controlled_io"])
                if (rpi_input["edge"] == "fall") ^ GPIO.input(gpio_pin):
                    rpi_output = [
                        r_out for r_out in self.rpi_outputs if self.to_int(r_out["index_id"]) == controlled_io
                    ].pop()
                    if rpi_output["output_type"] == "regular":
                        if rpi_output["gpio_i2c_enabled"]:
                            val = rpi_input["controlled_io_set_value"] != "low"
                            self.gpio_i2c_write(rpi_output, val)
                        else:
                            val = GPIO.LOW if rpi_input["controlled_io_set_value"] == "low" else GPIO.HIGH
                            self.write_gpio(self.to_int(rpi_output["gpio_pin"]), val)
        except Exception:
            self._logger.exception("Error handling initial GPIO control")

    def shell_command(self, command):
        try:
            stdout = (Popen(command, shell=True, stdout=PIPE).stdout).read()
            self._plugin_manager.send_plugin_message(
                self._identifier,
                {"is_msg": True, "msg": stdout, "msg_type": "success"},
            )
        except Exception:
            self._logger.exception("Could not execute shell script: %s", command)
            self._plugin_manager.send_plugin_message(
                self._identifier,
                {"is_msg": True, "msg": "Could not execute shell script", "msg_type": "error"},
            )

    def handle_gpio_control(self, channel):

        try:
            self._logger.debug("GPIO event triggered on channel %s", channel)
            for rpi_input in list(
                filter(lambda item: self.to_int(item["gpio_pin"]) == self.to_int(channel), self.rpi_inputs),
            ):
                gpio_pin = self.to_int(rpi_input["gpio_pin"])
                controlled_io = self.to_int(rpi_input["controlled_io"])
                if (rpi_input["edge"] == "fall") ^ GPIO.input(gpio_pin):
                    rpi_output = [
                        r_out for r_out in self.rpi_outputs if self.to_int(r_out["index_id"]) == controlled_io
                    ].pop()
                    if rpi_output["output_type"] == "regular":
                        if rpi_input["controlled_io_set_value"] == "toggle":
                            val = (
                                GPIO.LOW if GPIO.input(self.to_int(rpi_output["gpio_pin"])) == GPIO.HIGH else GPIO.HIGH
                            )
                        else:
                            val = GPIO.LOW if rpi_input["controlled_io_set_value"] == "low" else GPIO.HIGH
                        if rpi_output["gpio_i2c_enabled"]:
                            self.gpio_i2c_write(rpi_output, val)
                        else:
                            self.write_gpio(self.to_int(rpi_output["gpio_pin"]), val)
                        for notification in self.notifications:
                            if notification["gpioAction"]:
                                msg = (
                                    "GPIO control action caused by input "
                                    + str(rpi_input["label"])
                                    + ". Setting GPIO"
                                    + str(rpi_input["controlled_io"])
                                    + " to: "
                                    + str(rpi_input["controlled_io_set_value"])
                                )
                                self.send_notification(msg)
                    if rpi_output["output_type"] == "gcode_output":
                        self.send_gcode_command(rpi_output["gcode"])
                        for notification in self.notifications:
                            if notification["gpioAction"]:
                                msg = (
                                    "GPIO control action caused by input "
                                    + str(rpi_input["label"])
                                    + ". Sending GCODE command"
                                )
                                self.send_notification(msg)
                    if rpi_output["output_type"] == "shell_output":
                        command = rpi_output["shell_script"]
                        self.shell_command(command)
        except Exception:
            self._logger.exception("Error handling GPIO control on channel %s", channel)

    def send_gcode_command(self, command):
        for line in command.split("\n"):
            if line:
                self._printer.commands(line.strip())
                self._logger.info("Sending GCODE command: %s", line.strip())
                time.sleep(0.2)

    def handle_printer_action(self, channel):
        try:
            for rpi_input in self.rpi_inputs:
                if (
                    channel == self.to_int(rpi_input["gpio_pin"])
                    and rpi_input["action_type"] == "printer_control"
                    and ((rpi_input["edge"] == "fall") ^ GPIO.input(self.to_int(rpi_input["gpio_pin"])))
                ):
                    if rpi_input["printer_action"] == "resume":
                        self._logger.info("Printer action resume.")
                        self._printer.resume_print()
                    elif rpi_input["printer_action"] == "pause":
                        self._logger.info("Printer action pause.")
                        self._printer.pause_print()
                    elif rpi_input["printer_action"] == "cancel":
                        self._logger.info("Printer action cancel.")
                        self._printer.cancel_print()
                    elif rpi_input["printer_action"] == "toggle":
                        self._logger.info("Printer action toggle.")
                        if self._printer.is_operational():
                            self._printer.toggle_pause_print()
                        else:
                            self._printer.connect()
                    elif rpi_input["printer_action"] == "start":
                        self._logger.info("Printer action start.")
                        self._printer.start_print()
                    elif rpi_input["printer_action"] == "toggle_job":
                        self._logger.info("Printer action toggle_job.")
                        if self._printer.is_operational():
                            if self._printer.is_printing():
                                self._printer.cancel_print()
                            elif self._printer.is_ready():
                                self._printer.start_print()
                        else:
                            self._printer.connect()
                    elif rpi_input["printer_action"] == "stop_temp_hum_control":
                        self._logger.info("Printer action stopping temperature control.")
                        for rpi_output in self.rpi_outputs:
                            if rpi_output["auto_shutdown"] and rpi_output["output_type"] == "temp_hum_control":
                                rpi_output["temp_ctr_set_value"] = 0
                        self.handle_temp_hum_control()
                    for notification in self.notifications:
                        if notification["printer_action"]:
                            msg = (
                                "Printer action: "
                                + rpi_input["printer_action"]
                                + " caused by input: "
                                + str(rpi_input["label"])
                            )
                            self.send_notification(msg)
        except Exception:
            self._logger.exception("Error handling printer action on channel %s", channel)

    def write_gpio(self, gpio, value, queue_id=None):
        try:
            GPIO.output(gpio, value)
            if queue_id is not None:
                self._logger.debug("Running scheduled queue id %s", queue_id)
            self._logger.debug("Writing on GPIO: %s value %s", gpio, value)
            self.update_ui()
            if queue_id is not None:
                self.stop_queue_item(queue_id)
        except Exception:
            self._logger.exception("Error writing on pin %s", gpio)

    def write_pwm(self, gpio, pwm_value, queue_id=None):
        try:
            if queue_id is not None:
                self._logger.debug("running scheduled queue id %s", queue_id)
            for pwm in self.pwm_instances:
                if gpio in pwm:
                    pwm_object = pwm[gpio]
                    old_pwm_value = pwm.get("duty_cycle", -1)
                    if self.to_int(old_pwm_value) != self.to_int(pwm_value):
                        pwm["duty_cycle"] = pwm_value
                        pwm_object.start(pwm_value)  # should be changed back to pwm_object.ChangeDutyCycle() but this
                        # was causing errors.
                        self._logger.debug("Writing PWM on gpio: %s value %s", gpio, pwm_value)
                    self.update_ui()
                    if queue_id is not None:
                        self.stop_queue_item(queue_id)
                    break
        except Exception:
            self._logger.exception("Error writing PWM on pin %s", gpio)

    def get_output_list(self):
        return [
            self.to_int(rpi_output["gpio_pin"])
            for rpi_output in self.rpi_outputs
            if rpi_output["output_type"] == "regular"
        ]

    def send_notification(self, message):
        provider = self._settings.get(["notification_provider"])
        if provider == "ifttt":
            self.ifttt_notification(message)

    def ifttt_notification(self, message):
        event = self._settings.get(["notification_event_name"])
        api_key = self._settings.get(["notification_api_key"])
        self._logger.debug("Sending IFTTT notification for event %s: %s", event, message)
        try:
            response = requests.post(
                f"https://maker.ifttt.com/trigger/{event}/with/key/{api_key}/",
                data={"value1": message},
                timeout=(3.05, 7),
            )
        except requests.exceptions.RequestException as ex:
            self._logger.warning("Could not send IFTTT notification: %s", type(ex).__name__)
            return
        if not response.ok:
            self._logger.warning("IFTTT rejected the notification (HTTP %s): %s", response.status_code, response.text)

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
                    delay_seconds = self.get_startup_delay_from_output(rpi_output)
                    self.schedule_auto_startup_outputs(rpi_output, delay_seconds)
                if rpi_output["toggle_timer"] and rpi_output["output_type"] in ("regular", "pwm"):
                    self.toggle_output(rpi_output["index_id"], True)
                if self.is_hour(rpi_output["shutdown_time"]):
                    shutdown_delay_seconds = self.get_shutdown_delay_from_output(rpi_output)
                    self.schedule_auto_shutdown_outputs(rpi_output, shutdown_delay_seconds)
            self.run_tasks()
            self.update_ui()

        elif event == Events.PRINT_DONE:
            self.stop_filament_detection()
            self.print_complete = True
            for rpi_output in self.rpi_outputs:
                shutdown_time = rpi_output["shutdown_time"]
                if rpi_output["output_type"] == "pwm" and rpi_output["pwm_temperature_linked"]:
                    rpi_output["duty_cycle"] = rpi_output["default_duty_cycle"]
                if rpi_output["auto_shutdown"] and not self.is_hour(shutdown_time):
                    delay_seconds = self.to_float(shutdown_time)
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
                    if rpi_output["output_type"] == "pwm" and rpi_output["pwm_temperature_linked"]:
                        rpi_output["duty_cycle"] = rpi_output["default_duty_cycle"]
                    if rpi_output["auto_shutdown"] and not self.is_hour(shutdown_time):
                        delay_seconds = self.to_float(shutdown_time)
                        self.schedule_auto_shutdown_outputs(rpi_output, delay_seconds)
                        if rpi_output["output_type"] == "temp_hum_control":
                            rpi_output["temp_ctr_set_value"] = 0
            self.run_tasks()

        if event == Events.PRINT_DONE:
            for notification in self.notifications:
                if notification["printFinish"]:
                    file_name = Path(payload["path"]).name
                    elapsed_time_in_seconds = payload["time"]
                    elapsed_time = octoprint.util.get_formatted_timedelta(timedelta(seconds=elapsed_time_in_seconds))
                    msg = f"Print job finished: {file_name} printed in {elapsed_time}"
                    self.send_notification(msg)

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
            value = bool(rpi_output["active_low"])
            self.add_regular_output_to_queue(shutdown_delay_seconds, rpi_output, value, suffix)
        if rpi_output["output_type"] == "ledstrip":
            self.ledstrip_set_rgb(rpi_output)
        if rpi_output["output_type"] == "pwm" and not rpi_output["pwm_temperature_linked"]:
            value = 0
            self.add_pwm_output_to_queue(shutdown_delay_seconds, rpi_output, value, suffix)
        if rpi_output["output_type"] == "pwm" and rpi_output["pwm_temperature_linked"]:
            self.schedule_pwm_duty_on_queue(shutdown_delay_seconds, rpi_output, 0, suffix)
        if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
            self.add_neopixel_output_to_queue(rpi_output, shutdown_delay_seconds, 0, 0, 0, suffix)
        if rpi_output["output_type"] == "temp_hum_control":
            value = 0
            self.add_temperature_output_temperature_queue(shutdown_delay_seconds, rpi_output, value, suffix)
        self._logger.debug("Events scheduled to run %s", self.event_queue)

    def ledstrip_set_rgb(self, rpi_output, rgb=None):
        clk = rpi_output["ledstrip_gpio_clk"]
        data = rpi_output["ledstrip_gpio_dat"]
        if clk is not None and data is not None:
            ledstrip = LEDStrip(self.to_int(clk), self.to_int(data))
            if rgb is None:
                red, green, blue = self.get_color_from_rgb(rpi_output["default_ledstrip_color"])
            else:
                red, green, blue = self.get_color_from_rgb(rgb)

            self._logger.info("LEDSTRIP set rgb color: %s, %s, %s", red, green, blue)
            ledstrip.setcolourrgb(self.to_int(red), self.to_int(green), self.to_int(blue))
            rpi_output["ledstrip_color"] = f"rgb({red},{green},{blue})"

    def start_outpus_with_server(self):
        for rpi_output in self.rpi_outputs:
            if rpi_output["startup_with_server"]:
                gpio = self.to_int(rpi_output["gpio_pin"])
                if rpi_output["output_type"] == "regular":
                    value = not rpi_output["active_low"]
                    if rpi_output["gpio_i2c_enabled"]:
                        self.gpio_i2c_write(rpi_output, value)
                    else:
                        self.write_gpio(gpio, value)
                if rpi_output["output_type"] == "ledstrip":
                    self.ledstrip_set_rgb(rpi_output)
                if rpi_output["output_type"] == "pwm" and not rpi_output["pwm_temperature_linked"]:
                    value = self.to_int(rpi_output["default_duty_cycle"])
                    self.write_pwm(gpio, value)
                if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
                    red, green, blue = self.get_color_from_rgb(rpi_output["default_neopixel_color"])
                    led_count = rpi_output["neopixel_count"]
                    led_brightness = rpi_output["neopixel_brightness"]
                    address = rpi_output["microcontroller_address"]
                    index_id = self.to_int(rpi_output["index_id"])
                    neopixel_direct = rpi_output["output_type"] == "neopixel_direct"
                    self.send_neopixel_command(
                        self.to_int(rpi_output["gpio_pin"]),
                        led_count,
                        led_brightness,
                        red,
                        green,
                        blue,
                        address,
                        neopixel_direct,
                        index_id,
                    )
                if rpi_output["output_type"] == "temp_hum_control":
                    rpi_output["temp_ctr_set_value"] = rpi_output["temp_ctr_default_value"]

    def schedule_auto_startup_outputs(self, rpi_output, delay_seconds):
        suffix = "auto_startup"
        if rpi_output["output_type"] == "regular":
            value = not rpi_output["active_low"]
            self.add_regular_output_to_queue(delay_seconds, rpi_output, value, suffix)
        if rpi_output["output_type"] == "ledstrip":
            self.ledstrip_set_rgb(rpi_output)
        if rpi_output["output_type"] == "pwm" and not rpi_output["pwm_temperature_linked"]:
            value = self.to_int(rpi_output["default_duty_cycle"])
            self.add_pwm_output_to_queue(delay_seconds, rpi_output, value, suffix)
        if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
            red, green, blue = self.get_color_from_rgb(rpi_output["default_neopixel_color"])
            self.add_neopixel_output_to_queue(rpi_output, delay_seconds, red, green, blue, suffix)
        if rpi_output["output_type"] == "temp_hum_control":
            value = rpi_output["temp_ctr_default_value"]
            self.add_temperature_output_temperature_queue(delay_seconds, rpi_output, value, suffix)
        self._logger.debug("Events scheduled to run %s", self.event_queue)

    def get_color_from_rgb(self, string_color):
        if not string_color:
            return 0, 0, 0
        string_color = string_color.replace("rgb(", "")
        red = string_color[: string_color.index(",")]
        string_color = string_color[string_color.index(",") + 1 :]
        green = string_color[: string_color.index(",")]
        string_color = string_color[string_color.index(",") + 1 :]
        blue = string_color[: string_color.index(")")]
        return red, green, blue

    def get_shutdown_delay_from_output(self, rpi_output):
        shutdown_time = rpi_output["shutdown_time"]

        shut_down_date_time = self.create_date(shutdown_time)

        if shut_down_date_time < datetime.now():
            shut_down_date_time = shut_down_date_time + timedelta(days=1)

        return (shut_down_date_time - datetime.now()).total_seconds()

    def add_neopixel_output_to_queue(self, rpi_output, delay_seconds, red, green, blue, suffix):
        gpio_pin = rpi_output["gpio_pin"]
        led_count = rpi_output["neopixel_count"]
        led_brightness = rpi_output["neopixel_brightness"]
        address = rpi_output["microcontroller_address"]
        neopixel_direct = rpi_output["output_type"] == "neopixel_direct"
        index_id = self.to_int(rpi_output["index_id"])

        queue_id = f"{index_id}_{suffix}"

        self._logger.debug("Scheduling neopixel output id %s for on %s delay_seconds", queue_id, delay_seconds)

        thread = threading.Timer(
            delay_seconds,
            self.send_neopixel_command,
            args=[gpio_pin, led_count, led_brightness, red, green, blue, address, neopixel_direct, index_id, queue_id],
        )

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def add_pwm_output_to_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"{rpi_output['index_id']}_{suffix}"

        self._logger.debug("Scheduling pwm output id %s for on %s delay_seconds", queue_id, delay_seconds)

        thread = threading.Timer(
            delay_seconds,
            self.write_pwm,
            args=[self.to_int(rpi_output["gpio_pin"]), value, queue_id],
        )

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def schedule_pwm_duty_on_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"{rpi_output['index_id']}_pwm_linked_temp_{suffix}"
        thread = threading.Timer(delay_seconds, self.set_pwm_duty_cycle, args=[rpi_output, value, queue_id])

        self._logger.debug("Scheduling pwm linked temp output id %s on %s delay_seconds", queue_id, delay_seconds)

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def set_pwm_duty_cycle(self, rpi_output, value, queue_id):
        rpi_output["duty_cycle"] = value
        if queue_id is not None:
            self.stop_queue_item(queue_id)

    def add_regular_output_to_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"{rpi_output['index_id']}_{suffix}"

        self._logger.debug("Scheduling regular output id %s on %s delay_seconds", queue_id, delay_seconds)

        if rpi_output["gpio_i2c_enabled"]:
            thread = threading.Timer(delay_seconds, self.gpio_i2c_write, args=[rpi_output, value, queue_id])
        else:
            thread = threading.Timer(
                delay_seconds,
                self.write_gpio,
                args=[self.to_int(rpi_output["gpio_pin"]), value, queue_id],
            )

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def add_temperature_output_temperature_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"{rpi_output['index_id']}_{suffix}"
        self._logger.debug("Scheduling temperature control id %s on %s delay_seconds", queue_id, delay_seconds)

        thread = threading.Timer(
            delay_seconds,
            self.write_temperature_to_output,
            args=[self.to_int(rpi_output["index_id"]), value, queue_id],
        )

        self.event_queue.append({"queue_id": queue_id, "thread": thread})

    def write_temperature_to_output(self, rpi_output_index, value, queue_id=None):
        try:
            rpi_output = [
                r_out for r_out in self.rpi_outputs if self.to_int(r_out["index_id"]) == rpi_output_index
            ].pop()

            if rpi_output["output_type"] == "temp_hum_control":
                rpi_output["temp_ctr_set_value"] = value

                if queue_id is not None:
                    self._logger.debug("running scheduled queue id %s", queue_id)
                self._logger.debug("Setting temperature to output index: %s value %s", rpi_output["index_id"], value)

            self.update_ui()
            if queue_id is not None:
                self.stop_queue_item(queue_id)

        except Exception:
            self._logger.exception("Error setting temperature on output %s", rpi_output_index)

    def get_startup_delay_from_output(self, rpi_output):
        start_up_time = rpi_output["startup_time"]
        if self.is_hour(start_up_time):
            start_up_date_time = self.create_date(start_up_time)
            if start_up_date_time < datetime.now():
                delay_seconds = 0.0
            else:
                delay_seconds = (start_up_date_time - datetime.now()).total_seconds()
        else:
            delay_seconds = self.to_float(rpi_output["startup_time"])
        return delay_seconds

    # ~~ SettingsPlugin mixin
    def on_settings_save(self, data):
        outputs_before_save = self.get_output_list()
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.rpi_outputs = self._settings.get(["rpi_outputs"])
        self.rpi_inputs = self._settings.get(["rpi_inputs"])
        self.notifications = self._settings.get(["notifications"])
        outputs_after_save = self.get_output_list()

        common_pins = list(set(outputs_before_save) & set(outputs_after_save))

        for pin in (pin for pin in outputs_before_save if pin not in common_pins):
            self.clear_channel(pin)

        self.rpi_outputs_not_changed = common_pins
        self.clear_gpio()

        self._logger.debug("rpi_outputs: %s", self.rpi_outputs)
        self._logger.debug("rpi_inputs: %s", self.rpi_inputs)
        self.setup_gpio()
        self.configure_gpio()
        self.generate_temp_hum_control_status()

    def get_settings_defaults(self):
        return {
            "rpi_outputs": [],
            "rpi_inputs": [],
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
            "use_sudo": True,
            "neopixel_dma": 10,
            "debug": False,
            "gcode_control": False,
            "debug_temperature_log": False,
            "use_board_pin_number": False,
            "notification_provider": "disabled",
            "notification_api_key": "",
            "notification_event_name": "printer_event",
            "notifications": [
                {
                    "printFinish": True,
                    "filamentChange": True,
                    "printer_action": True,
                    "temperatureAction": True,
                    "gpioAction": True,
                },
            ],
        }

    # ~~ TemplatePlugin
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
        if self._settings.get(["gcode_control"]) is False:
            return

        if cmd.strip().startswith("ENC"):
            self._logger.debug("Gcode queuing: %s", cmd)
            index_id = self.to_int(self.get_gcode_value(cmd, "O"))
            for output in [item for item in self.rpi_outputs if item["index_id"] == index_id]:
                if output["output_type"] == "regular":
                    set_value = self.to_int(self.get_gcode_value(cmd, "S"))
                    set_value = self.constrain(set_value, 0, 1)
                    value = set_value == 1
                    value = (not value) if output["active_low"] else value
                    if output["gpio_i2c_enabled"]:
                        self.gpio_i2c_write(output, value)
                    else:
                        self.write_gpio(self.to_int(output["gpio_pin"]), value)
                    comm_instance._log(f"Setting REGULAR output {index_id} to value {value}")
                    return
                if output["output_type"] == "pwm":
                    set_value = self.to_int(self.get_gcode_value(cmd, "S"))
                    set_value = self.constrain(set_value, 0, 100)
                    output["duty_cycle"] = set_value
                    self.write_pwm(self.to_int(output["gpio_pin"]), set_value)
                    comm_instance._log(f"Setting PWM output {index_id} to value {set_value}")
                    return
                if output["output_type"] == "neopixel_indirect" or output["output_type"] == "neopixel_direct":
                    red = self.get_gcode_value(cmd, "R")
                    green = self.get_gcode_value(cmd, "G")
                    blue = self.get_gcode_value(cmd, "B")

                    led_count = output["neopixel_count"]
                    led_brightness = output["neopixel_brightness"]
                    address = output["microcontroller_address"]

                    index_id = self.to_int(output["index_id"])

                    neopixel_direct = output["output_type"] == "neopixel_direct"

                    self.send_neopixel_command(
                        self.to_int(output["gpio_pin"]),
                        led_count,
                        led_brightness,
                        red,
                        green,
                        blue,
                        address,
                        neopixel_direct,
                        index_id,
                    )
                    comm_instance._log(f"Setting NEOPIXEL output {index_id} to red: {red} green: {green} blue: {blue}")
                    return
                if output["output_type"] == "temp_hum_control":
                    set_value = self.to_float(self.get_gcode_value(cmd, "S"))
                    should_wait = self.to_int(self.get_gcode_value(cmd, "W"))
                    if should_wait == 1 and self._printer.is_printing():
                        self._printer.pause_print()
                        self.waiting_temperature.append(index_id)
                    output["temp_ctr_set_value"] = set_value
                    self.update_ui_set_temperature()
                    self.handle_temp_hum_control()
                    comm_instance._log(f"Setting TEMP/HUM control output {index_id} to value {set_value}")
                    return

    def get_graph_data(self, comm, parsed_temps):
        for sensor in list(filter(lambda item: item["input_type"] == "temperature_sensor", self.rpi_inputs)):
            if sensor["show_graph_temp"]:
                parsed_temps[str(sensor["label"])] = (sensor["temp_sensor_temp"], None)
            if sensor["show_graph_humidity"]:
                parsed_temps[str(sensor["label"]) + " Humidity"] = (sensor["temp_sensor_humidity"], None)

        return parsed_temps


__plugin_name__ = "Enclosure Plugin"
__plugin_pythoncompat__ = ">=3.7,<4"
__plugin_implementation__ = EnclosurePlugin()
__plugin_hooks__ = {
    "octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.hook_gcode_queuing,
    "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
    "octoprint.comm.protocol.temperatures.received": (__plugin_implementation__.get_graph_data, 1),
}
