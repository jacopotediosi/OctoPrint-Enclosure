import contextlib
import functools
import logging
import sys
from datetime import timedelta
from pathlib import Path

import octoprint.plugin
import octoprint.util
import smbus2
from octoprint.events import Events
from octoprint.logging.handlers import CleaningTimedRotatingFileHandler

from .actions import Actions
from .api import Api
from .automations import (
    AutomationError,
    Automations,
    FilamentAutomation,
    RuleAutomation,
    TemperatureTrigger,
)
from .control_loop import ControlLoop
from .core import Frontend, PluginContext, Scheduler, Settings
from .core.migrations import migrate_settings
from .gcode_commands import EncDevHandler, EncHandler
from .hardware import dummy_gpio, dummy_i2c, gpio
from .inputs import GpioInputs, SensorError, SensorPoller, Sensors
from .integrations import Mqtt
from .notifications import Notifications, NotificationType
from .output_executor import OutputExecutor
from .outputs import (
    LedstripOutput,
    NeopixelDirectOutput,
    NeopixelIndirectOutput,
    OutputError,
    Outputs,
    PwmOutput,
    RegularOutput,
    RegularSetState,
    ThermostatDeviceType,
    ThermostatOutput,
)
from .utils import (
    parse_hhmm,
    parse_rgb,
    seconds_until_next,
    seconds_until_today_at,
    to_float,
    to_int,
)


class EnclosurePlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.BlueprintPlugin,
    octoprint.plugin.EventHandlerPlugin,
):
    rpi_inputs = []
    rpi_outputs = []
    actions = []
    automations = []
    failing_sensors = set()
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

        # Init general plugin components
        self._enclosure_settings = Settings(self._settings)
        self._frontend = Frontend(self._plugin_manager, self._identifier)

        # Init hardware
        self.development_mode = self._enclosure_settings.development_mode
        if self.development_mode:
            self._gpio = dummy_gpio
            self._i2c = dummy_i2c
            self._logger.warning("Development mode is enabled: GPIO and I2C (pins, sensors, etc) are simulated")
        else:
            self._gpio = gpio
            self._i2c = smbus2

        # Init inputs, outputs, actions and automations
        self._sensors = Sensors(self._logger, dummy=self.development_mode)
        self._gpio_inputs = GpioInputs(self._gpio, self.handle_gpio_input, self._logger)
        self._outputs = Outputs(self._gpio, self._i2c, self._logger)
        self._actions = Actions(self._printer, self._frontend, self._logger)
        self._automations = Automations(self._logger)

        # Init notifications
        self._notifications = Notifications(self._enclosure_settings, self._logger)

        # Init integrations
        self._mqtt = Mqtt(self._plugin_manager, self._logger)

        # Init threads
        self._sensor_poller = SensorPoller(self._sensors, self.handle_sensor_reading, self._logger)
        self._scheduler = Scheduler(self._logger)
        self._output_executor = OutputExecutor(self._outputs, self._logger, update_ui_outputs=self.send_ui_outputs)
        self._control_loop = ControlLoop(
            self._gpio_inputs,
            self._outputs,
            self._actions,
            self._automations,
            self._output_executor,
            self._notifications,
            self._printer,
            self._frontend,
            self._enclosure_settings,
            self._logger,
            get_sensor_data=self.get_sensor_data,
        )

        # Init the plugin context
        self._plugin_context = PluginContext(
            identifier=self._identifier,
            basefolder=self._basefolder,
            logger=self._logger,
            settings=self._enclosure_settings,
            frontend=self._frontend,
            printer=self._printer,
            gpio=self._gpio,
            i2c=self._i2c,
            sensors=self._sensors,
            gpio_inputs=self._gpio_inputs,
            outputs=self._outputs,
            actions=self._actions,
            automations=self._automations,
            output_executor=self._output_executor,
            scheduler=self._scheduler,
            sensor_poller=self._sensor_poller,
            control_loop=self._control_loop,
            notifications=self._notifications,
            mqtt=self._mqtt,
        )

        # Init G-code command handlers
        self._enc_handler = EncHandler(self._plugin_context, self.handle_temperature_command)
        self._encdev_handler = EncDevHandler(
            self._plugin_context,
            development_mode=self.development_mode,
            read_sensors_now=self.check_enclosure_temp,
            handle_event=self.on_event,
        )

        # Init the API
        self._api = Api(
            self._plugin_context,
            get_sensor_data=self.get_sensor_data,
            update_ui=self.update_ui,
            set_auto_startup_enabled=self.set_auto_startup_enabled,
            set_auto_shutdown_enabled=self.set_auto_shutdown_enabled,
            set_filament_sensor_enabled=self.set_filament_sensor_enabled,
        )

    def output_state_boolean(self, index_id, output_class):
        try:
            return self._outputs.get(index_id, output_class).is_on()
        except OutputError:
            return "ERROR: Unable to read pin"
        except Exception:
            self._logger.exception("Error reading output %s", index_id)
            return "ERROR: Unable to read pin"

    # ~~ StartupPlugin mixin
    def on_after_startup(self):
        self._mqtt.load_helpers()

        self.rpi_inputs = self._enclosure_settings.rpi_inputs
        self.rpi_outputs = self._enclosure_settings.rpi_outputs
        self.actions = self._enclosure_settings.actions
        self.automations = self._enclosure_settings.automations

        self._sensor_poller.load(self.get_sensor_inputs())
        self._gpio_inputs.load(self.get_gpio_inputs())
        self.setup_gpio_mode()
        self._output_executor.load_outputs(self.rpi_outputs, wait=True)
        if self.development_mode:
            self.link_dummy_sensors()
        self._actions.load(self.actions)
        self._automations.load(self.automations)
        self.warn_missing_linked_sensors()

        self.setup_input_pins()
        self.start_outpus_with_server()

        self._sensor_poller.start()
        self._control_loop.start()

    # ~~ ShutdownPlugin mixin
    def on_shutdown(self):
        try:
            self._control_loop.stop()
        except Exception:
            self._logger.exception("Error stopping the Control Loop")

        try:
            self._scheduler.stop()
        except Exception:
            self._logger.exception("Error stopping the scheduler")

        try:
            self._output_executor.shutdown()
        except Exception:
            self._logger.exception("Error shutting down the outputs")

        try:
            self._notifications.stop()
        except Exception:
            self._logger.exception("Error stopping the notifications")

    # ~~ SettingsPlugin mixin
    def get_settings_version(self):
        return 11

    def on_settings_migrate(self, target, current=None):
        migrate_settings(target, current, self._settings, self._logger)

    # ~~ BlueprintPlugin mixin
    def get_blueprint(self):
        return self._api.get_blueprint()

    def is_blueprint_csrf_protected(self):
        return True

    def output_color(self, index_id, output_class):
        try:
            color = self._outputs.get(index_id, output_class).color
        except OutputError:
            color = None

        # Until a color is set, the output is shown as black
        red, green, blue = (0, 0, 0) if color is None else color

        return f"rgb({red},{green},{blue})"

    def get_sensor_inputs(self):
        return [rpi_input for rpi_input in self.rpi_inputs if rpi_input["input_type"] == "temperature_sensor"]

    def get_gpio_inputs(self):
        return [rpi_input for rpi_input in self.rpi_inputs if rpi_input["input_type"] == "gpio"]

    def warn_missing_linked_sensors(self):
        sensor_ids = {to_int(rpi_input["index_id"]) for rpi_input in self.get_sensor_inputs()}
        for rpi_output in self.rpi_outputs:
            if rpi_output["output_type"] != "temp_hum_control":
                continue
            if to_int(rpi_output["linked_temp_sensor"]) not in sensor_ids:
                self._logger.warning(
                    "Output %s is linked to sensor %s, which doesn't exist",
                    rpi_output["index_id"],
                    rpi_output["linked_temp_sensor"],
                )
        for automation in self.automations:
            is_temperature_rule = (
                automation["automation_type"] == "rule" and automation["trigger_type"] == "temperature"
            )
            if not is_temperature_rule and automation["automation_type"] != "pwm_temperature_linked":
                continue
            if to_int(automation["linked_temp_sensor"]) not in sensor_ids:
                self._logger.warning(
                    "Automation %s is linked to sensor %s, which doesn't exist",
                    automation["index_id"],
                    automation["linked_temp_sensor"],
                )

    def link_dummy_sensors(self):
        for thermostat in self._outputs.get_all(ThermostatOutput):
            try:
                dummy = self._sensors.get_dummy(thermostat.config.linked_temp_sensor)
            except LookupError:
                continue
            if thermostat.config.temp_ctr_type is ThermostatDeviceType.HEATER:
                dummy.is_heater_on = thermostat.is_on
            elif thermostat.config.temp_ctr_type is ThermostatDeviceType.COOLER:
                dummy.is_cooler_on = thermostat.is_on
            elif thermostat.config.temp_ctr_type is ThermostatDeviceType.DEHUMIDIFIER:
                dummy.is_dehumidifier_on = thermostat.is_on

    def get_pwm_temperature_linked_settings(self, output_id=None):
        return [
            item
            for item in self.automations
            if item["automation_type"] == "pwm_temperature_linked"
            and (output_id is None or to_int(item["output"]) == output_id)
        ]

    def is_pwm_linked(self, index_id):
        return bool(self.get_pwm_temperature_linked_settings(to_int(index_id)))

    def check_enclosure_temp(self):
        """Read every sensor now, then take the decisions on the readings."""
        self._sensor_poller.read_all()
        self._control_loop.evaluate()

    def handle_sensor_reading(self, index_id, sensor_reading):
        # The input may have been removed by a settings save while its sensor was being read
        sensor = next((item for item in self.get_sensor_inputs() if item["index_id"] == index_id), None)
        if sensor is None:
            return

        if sensor_reading.error is not None:
            self.handle_sensor_failure(sensor, sensor_reading.error)
        else:
            temp, hum, _ = self.convert_reading(sensor, sensor_reading.reading)
            self.handle_sensor_recovery(sensor)
            self._mqtt.publish_sensor_reading(sensor["label"], temp, hum)

        self.update_ui_readings()
        self._control_loop.evaluate_reading(index_id)

    def get_sensor_data(self):
        readings = self._sensor_poller.get_readings()

        sensor_data = []
        for sensor in self.get_sensor_inputs():
            sensor_reading = readings.get(sensor["index_id"])
            if sensor_reading is None or sensor_reading.error is not None:
                temp = hum = airquality = None
            else:
                temp, hum, airquality = self.convert_reading(sensor, sensor_reading.reading)

            sensor_data.append(
                {
                    "index_id": sensor["index_id"],
                    "temperature": temp,
                    "humidity": hum,
                    "airquality": airquality,
                },
            )

        return sensor_data

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
                if self._printer.is_printing() or self._printer.is_paused():
                    on = self._output_executor.switch_output(
                        index_id,
                        RegularSetState.ON if first_run else RegularSetState.TOGGLE,
                        wait=True,
                    )
                    time_delay = to_int(output["toggle_timer_on"]) if on else to_int(output["toggle_timer_off"])
                    self._scheduler.schedule(
                        f"output:{index_id}:toggle_timer",
                        time_delay,
                        functools.partial(self.toggle_output, index_id),
                    )
                else:
                    self._output_executor.switch_output(index_id, RegularSetState.OFF)
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

                if self._printer.is_printing() or self._printer.is_paused():
                    self._output_executor.write_pwm(index_id, write_value)
                    self._scheduler.schedule(
                        f"output:{index_id}:toggle_timer",
                        time_delay,
                        functools.partial(self.toggle_output, index_id),
                    )
                else:
                    self._output_executor.write_pwm(index_id, 0)
                return

    def update_ui(self):
        self.update_ui_readings()
        self.update_ui_filament_sensors()
        self.update_ui_outputs()
        self.update_ui_targets()

    def update_ui_readings(self):
        self._frontend.update_readings(self.get_sensor_data())

    def update_ui_filament_sensors(self):
        try:
            sensor_status = []
            for automation_settings in self.automations:
                if automation_settings["automation_type"] == "filament":
                    index = to_int(automation_settings["index_id"])
                    with contextlib.suppress(AutomationError):
                        value = self._automations.get(index, FilamentAutomation).enabled
                        sensor_status.append({"index_id": index, "filament_sensor_enabled": value})
            self._frontend.update_filament_sensors(sensor_status)
        except Exception:
            self._logger.exception("Error sending input status to the UI")

    def update_ui_targets(self):
        self._control_loop.update_ui_targets()

    def update_ui_outputs(self):
        self._output_executor.update_ui_outputs()

    def send_ui_outputs(self):
        try:
            regular_status = []
            pwm_status = []
            neopixel_status = []
            ledstrip_status = []
            thermostat_status = []
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
                    val = self.output_state_boolean(index, ThermostatOutput) is True
                    thermostat_status.append(
                        {"index_id": index, "status": val, "auto_startup": startup, "auto_shutdown": shutdown},
                    )
                if output["output_type"] == "neopixel_indirect" or output["output_type"] == "neopixel_direct":
                    neopixel_class = (
                        NeopixelDirectOutput if output["output_type"] == "neopixel_direct" else NeopixelIndirectOutput
                    )
                    val = self.output_color(index, neopixel_class)
                    neopixel_status.append(
                        {"index_id": index, "color": val, "auto_startup": startup, "auto_shutdown": shutdown},
                    )
                if output["output_type"] == "ledstrip":
                    val = self.output_color(index, LedstripOutput)
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
                thermostats=thermostat_status,
            )
        except Exception:
            self._logger.exception("Error sending outputs status to the UI")

    def convert_reading(self, sensor, reading):
        temperature = reading.temperature
        if temperature is not None and sensor["use_fahrenheit"]:
            temperature = temperature * 1.8 + 32

        temperature = None if temperature is None else round(float(temperature), 1)
        humidity = None if reading.humidity is None else round(float(reading.humidity), 1)
        airquality = None if reading.airquality is None else round(float(reading.airquality), 1)

        return temperature, humidity, airquality

    def setup_gpio_mode(self):
        try:
            current_mode = self._gpio.getmode()
            set_mode = self._gpio.BOARD if self._enclosure_settings.use_board_pin_number else self._gpio.BCM
            if current_mode is None:
                inputs = list(filter(lambda item: item["input_type"] == "gpio", self.rpi_inputs))
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
                gpios = inputs + outputs
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

    def setup_input_pins(self):
        try:
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

    def handle_gpio_input(self, input_id, level):
        self._control_loop.evaluate_gpio_input_edge(input_id, level)

    def set_thermostat_target(self, index_id, target):
        self._control_loop.set_thermostat_target(index_id, to_float(target))

    def handle_temperature_command(self, index_id, temperature, wait):
        self.set_thermostat_target(index_id, temperature)
        if wait and self._printer.is_printing():
            self._printer.pause_print()
            self._control_loop.wait_for_temperature(index_id)

    def set_auto_startup_enabled(self, index_id, enabled):
        if not enabled:
            self._scheduler.cancel(f"output:{index_id}:auto_startup")
        for output in self.rpi_outputs:
            if index_id == to_int(output["index_id"]):
                output["auto_startup"] = enabled
                self._logger.info("Setting auto startup for output %s to : %s", str(index_id), enabled)
        self._enclosure_settings.rpi_outputs = self.rpi_outputs
        self.update_ui_outputs()

    def set_auto_shutdown_enabled(self, index_id, enabled):
        if not enabled:
            self._scheduler.cancel(f"output:{index_id}:auto_shutdown")
        for output in self.rpi_outputs:
            if index_id == to_int(output["index_id"]):
                output["auto_shutdown"] = enabled
                self._logger.info("Setting auto shutdown for output %s to : %s", str(index_id), enabled)
        self._enclosure_settings.rpi_outputs = self.rpi_outputs
        self.update_ui_outputs()

    def set_filament_sensor_enabled(self, input_id, enabled):
        for automation_settings in self.automations:
            if (
                automation_settings["automation_type"] == "filament"
                and to_int(automation_settings["input"]) == input_id
            ):
                automation_settings["filament_sensor_enabled"] = enabled
                with contextlib.suppress(AutomationError):
                    index_id = to_int(automation_settings["index_id"])
                    self._automations.get(index_id, FilamentAutomation).enabled = bool(enabled)
                self._logger.info("Setting filament sensor for input %s to : %s", str(input_id), enabled)
        self._enclosure_settings.automations = self.automations
        self.update_ui_filament_sensors()

    # ~~ EventPlugin mixin
    def on_event(self, event, payload):
        self._control_loop.evaluate_octoprint_event(event)

        if event == Events.PRINT_STARTED:
            self._scheduler.cancel_all()
            for rpi_output in self.rpi_outputs:
                if rpi_output["auto_startup"]:
                    startup_time = rpi_output["startup_time"]
                    startup_time_of_day = parse_hhmm(str(startup_time))
                    delay_seconds = (
                        to_float(startup_time)
                        if startup_time_of_day is None
                        else seconds_until_today_at(startup_time_of_day)
                    )
                    self.schedule_auto_startup_outputs(rpi_output, delay_seconds)
                if rpi_output["toggle_timer"] and rpi_output["output_type"] in ("regular", "pwm"):
                    self.toggle_output(rpi_output["index_id"], True)
                shutdown_time_of_day = parse_hhmm(str(rpi_output["shutdown_time"]))
                if shutdown_time_of_day is not None:
                    shutdown_delay_seconds = seconds_until_next(shutdown_time_of_day)
                    self.schedule_auto_shutdown_outputs(rpi_output, shutdown_delay_seconds)

        elif event == Events.PRINT_DONE:
            for rpi_output in self.rpi_outputs:
                shutdown_time = rpi_output["shutdown_time"]
                if rpi_output["auto_shutdown"] and parse_hhmm(str(shutdown_time)) is None:
                    delay_seconds = to_float(shutdown_time)
                    self.schedule_auto_shutdown_outputs(rpi_output, delay_seconds)

        elif event in (Events.PRINT_CANCELLED, Events.PRINT_FAILED):
            self._scheduler.cancel_all()
            for rpi_output in self.rpi_outputs:
                if rpi_output["shutdown_on_failed"]:
                    shutdown_time = rpi_output["shutdown_time"]
                    if rpi_output["auto_shutdown"] and parse_hhmm(str(shutdown_time)) is None:
                        delay_seconds = to_float(shutdown_time)
                        self.schedule_auto_shutdown_outputs(rpi_output, delay_seconds)
                        if rpi_output["output_type"] == "temp_hum_control":
                            self.set_thermostat_target(to_int(rpi_output["index_id"]), 0)

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

    def schedule_auto_shutdown_outputs(self, rpi_output, shutdown_delay_seconds):
        suffix = "auto_shutdown"
        if rpi_output["output_type"] == "regular":
            self.add_regular_output_to_queue(shutdown_delay_seconds, rpi_output, RegularSetState.OFF, suffix)
        if rpi_output["output_type"] == "ledstrip":
            red, green, blue = parse_rgb(rpi_output["default_ledstrip_color"])
            self._output_executor.set_color(to_int(rpi_output["index_id"]), to_int(red), to_int(green), to_int(blue))
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

    def start_outpus_with_server(self):
        for rpi_output in self.rpi_outputs:
            if rpi_output["startup_with_server"]:
                if rpi_output["output_type"] == "regular":
                    self._output_executor.switch_output(rpi_output["index_id"], RegularSetState.ON)
                if rpi_output["output_type"] == "ledstrip":
                    red, green, blue = parse_rgb(rpi_output["default_ledstrip_color"])
                    self._output_executor.set_color(
                        to_int(rpi_output["index_id"]),
                        to_int(red),
                        to_int(green),
                        to_int(blue),
                    )
                if rpi_output["output_type"] == "pwm" and not self.is_pwm_linked(rpi_output["index_id"]):
                    value = to_int(rpi_output["default_duty_cycle"])
                    self._output_executor.write_pwm(rpi_output["index_id"], value)
                if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
                    red, green, blue = parse_rgb(rpi_output["default_neopixel_color"])
                    self._output_executor.set_color(
                        to_int(rpi_output["index_id"]),
                        to_int(red),
                        to_int(green),
                        to_int(blue),
                    )
                if rpi_output["output_type"] == "temp_hum_control":
                    index_id = to_int(rpi_output["index_id"])
                    self.set_thermostat_target(index_id, rpi_output["temp_ctr_default_value"])

    def schedule_auto_startup_outputs(self, rpi_output, delay_seconds):
        suffix = "auto_startup"
        if rpi_output["output_type"] == "regular":
            self.add_regular_output_to_queue(delay_seconds, rpi_output, RegularSetState.ON, suffix)
        if rpi_output["output_type"] == "ledstrip":
            red, green, blue = parse_rgb(rpi_output["default_ledstrip_color"])
            self._output_executor.set_color(to_int(rpi_output["index_id"]), to_int(red), to_int(green), to_int(blue))
        if rpi_output["output_type"] == "pwm" and not self.is_pwm_linked(rpi_output["index_id"]):
            value = to_int(rpi_output["default_duty_cycle"])
            self.add_pwm_output_to_queue(delay_seconds, rpi_output, value, suffix)
        if rpi_output["output_type"] == "neopixel_indirect" or rpi_output["output_type"] == "neopixel_direct":
            red, green, blue = parse_rgb(rpi_output["default_neopixel_color"])
            self.add_neopixel_output_to_queue(rpi_output, delay_seconds, red, green, blue, suffix)
        if rpi_output["output_type"] == "temp_hum_control":
            value = rpi_output["temp_ctr_default_value"]
            self.add_temperature_output_temperature_queue(delay_seconds, rpi_output, value, suffix)

    def add_neopixel_output_to_queue(self, rpi_output, delay_seconds, red, green, blue, suffix):
        queue_id = f"output:{to_int(rpi_output['index_id'])}:{suffix}"
        self._logger.debug("Scheduling neopixel output id %s for on %s delay_seconds", queue_id, delay_seconds)
        self._scheduler.schedule(
            queue_id,
            delay_seconds,
            functools.partial(
                self._output_executor.set_color,
                to_int(rpi_output["index_id"]),
                to_int(red),
                to_int(green),
                to_int(blue),
            ),
        )

    def add_pwm_output_to_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"output:{to_int(rpi_output['index_id'])}:{suffix}"
        self._logger.debug("Scheduling pwm output id %s for on %s delay_seconds", queue_id, delay_seconds)
        self._scheduler.schedule(
            queue_id,
            delay_seconds,
            functools.partial(self._output_executor.write_pwm, rpi_output["index_id"], value),
        )

    def schedule_pwm_duty_on_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"output:{to_int(rpi_output['index_id'])}:{suffix}"
        self._logger.debug("Scheduling pwm linked temp output id %s on %s delay_seconds", queue_id, delay_seconds)
        self._scheduler.schedule(
            queue_id,
            delay_seconds,
            functools.partial(self._output_executor.write_pwm, rpi_output["index_id"], value),
        )

    def add_regular_output_to_queue(self, delay_seconds, rpi_output, state, suffix):
        queue_id = f"output:{to_int(rpi_output['index_id'])}:{suffix}"
        self._logger.debug("Scheduling regular output id %s on %s delay_seconds", queue_id, delay_seconds)
        self._scheduler.schedule(
            queue_id,
            delay_seconds,
            functools.partial(self._output_executor.switch_output, rpi_output["index_id"], state),
        )

    def add_temperature_output_temperature_queue(self, delay_seconds, rpi_output, value, suffix):
        queue_id = f"output:{to_int(rpi_output['index_id'])}:{suffix}"
        self._logger.debug("Scheduling thermostat id %s on %s delay_seconds", queue_id, delay_seconds)
        self._scheduler.schedule(
            queue_id,
            delay_seconds,
            functools.partial(self.write_temperature_to_output, to_int(rpi_output["index_id"]), value),
        )

    def write_temperature_to_output(self, rpi_output_index, value):
        try:
            rpi_output = [r_out for r_out in self.rpi_outputs if to_int(r_out["index_id"]) == rpi_output_index].pop()

            if rpi_output["output_type"] == "temp_hum_control":
                self.set_thermostat_target(rpi_output_index, value)
                self._logger.debug("Setting temperature to output index: %s value %s", rpi_output["index_id"], value)

        except Exception:
            self._logger.exception("Error setting temperature on output %s", rpi_output_index)

    # ~~ SettingsPlugin mixin
    def on_settings_save(self, data):
        # Save the settings
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

        # Read from the saved settings
        self.rpi_inputs = self._enclosure_settings.rpi_inputs
        self._logger.debug("New rpi_inputs: %s", self.rpi_inputs)
        self.rpi_outputs = self._enclosure_settings.rpi_outputs
        self._logger.debug("New rpi_outputs: %s", self.rpi_outputs)
        self.actions = self._enclosure_settings.actions
        self._logger.debug("New actions: %s", self.actions)
        self.automations = self._enclosure_settings.automations
        self._logger.debug("New automations: %s", self.automations)

        # Update the sensor poller
        self._sensor_poller.load(self.get_sensor_inputs())

        # Set the GPIO mode
        self.setup_gpio_mode()

        # Release the pins of the GPIO inputs
        try:
            self._gpio_inputs.clear()
        except Exception:
            self._logger.exception("Error clearing GPIO")

        # Update outputs
        self._output_executor.load_outputs(self.rpi_outputs, wait=True)

        # Link outputs to dummy sensors
        if self.development_mode:
            self.link_dummy_sensors()

        # Update actions
        self._actions.load(self.actions)

        # Update automations
        self._automations.load(self.automations)
        self.warn_missing_linked_sensors()

        # Reload the GPIO inputs and set up the inputs pins
        self._gpio_inputs.load(self.get_gpio_inputs())
        self.setup_input_pins()

        # Take the decisions again on the new settings
        self._control_loop.evaluate_settings()

        # Update UI in every client
        self.update_ui()

    def get_settings_defaults(self):
        return {
            "rpi_inputs": [],
            "rpi_outputs": [],
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
            {
                "type": "navbar",
                "custom_bindings": True,
                "template": "enclosure_navbar_input.jinja2",
                "suffix": "_1",
                "classes": ["dropdown"],
            },
            {
                "type": "navbar",
                "custom_bindings": True,
                "template": "enclosure_navbar.jinja2",
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
        sensor_data = {item["index_id"]: item for item in self.get_sensor_data()}
        for sensor in self.get_sensor_inputs():
            reading = sensor_data.get(sensor["index_id"])
            if reading is None:
                continue
            if sensor["show_graph_temp"] and reading["temperature"] is not None:
                parsed_temps[str(sensor["label"])] = (reading["temperature"], None)
            if sensor["show_graph_humidity"] and reading["humidity"] is not None:
                parsed_temps[str(sensor["label"]) + " Humidity"] = (reading["humidity"], None)

        return parsed_temps
