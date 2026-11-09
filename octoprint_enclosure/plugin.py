import contextlib
import logging
import sys
from datetime import timedelta
from pathlib import Path

import octoprint.plugin
import octoprint.util
import smbus2
from octoprint.events import Events, all_events
from octoprint.logging.handlers import CleaningTimedRotatingFileHandler

from .actions import Actions
from .api import Api
from .automations import (
    Automation,
    AutomationError,
    Automations,
    RuleAutomation,
    TemperatureTrigger,
)
from .engine import ControlLoop, OutputExecutor, Scheduler
from .frontend import Frontend
from .gcode_commands import EncDevHandler, EncHandler
from .hardware import dummy_gpio, dummy_i2c, gpio
from .inputs import GpioInputs, InputType, SensorError, SensorPoller, Sensors
from .integrations import Mqtt
from .notifications import Notifications, NotificationType
from .outputs import Outputs, ThermostatDeviceType, ThermostatOutput
from .plugin_context import PluginContext
from .settings import Settings
from .settings.migrations import migrate_settings
from .utils import to_int


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
        self._sensors = Sensors(self._gpio, self._logger, dummy=self.development_mode)
        self._gpio_inputs = GpioInputs(self._gpio, self.handle_gpio_input, self._logger)
        self._outputs = Outputs(self._gpio, self._i2c, self._logger)
        self._automations = Automations(self._logger)
        self._sensor_poller = SensorPoller(self._sensors, self.handle_sensor_reading, self._logger)
        self._frontend = Frontend(
            self._plugin_manager,
            self._identifier,
            self._enclosure_settings,
            self._outputs,
            self._automations,
            self._sensor_poller,
            self._logger,
        )
        self._actions = Actions(self._printer, self._frontend, self._logger)

        # Init notifications
        self._notifications = Notifications(self._enclosure_settings, self._logger)

        # Init integrations
        self._mqtt = Mqtt(self._plugin_manager, self._logger)

        # Init threads
        self._scheduler = Scheduler(self._logger)
        self._output_executor = OutputExecutor(self._outputs, self._frontend, self._logger)
        self._control_loop = ControlLoop(
            self._gpio_inputs,
            self._sensor_poller,
            self._outputs,
            self._actions,
            self._automations,
            self._output_executor,
            self._scheduler,
            self._notifications,
            self._printer,
            self._frontend,
            self._enclosure_settings,
            self._logger,
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

        # Init API
        self._api = Api(self._plugin_context, set_automation_enabled=self.set_automation_enabled)

    # ~~ StartupPlugin mixin
    def on_after_startup(self):
        self._mqtt.load_helpers()

        self.rpi_inputs = self._enclosure_settings.rpi_inputs
        self.rpi_outputs = self._enclosure_settings.rpi_outputs
        self.actions = self._enclosure_settings.actions
        self.automations = self._enclosure_settings.automations

        self._sensor_poller.load(self.get_sensor_inputs_settings())
        self._gpio_inputs.load(self.get_gpio_inputs_settings())
        self._output_executor.load_outputs(self.rpi_outputs, wait=True)
        if self.development_mode:
            self.link_dummy_sensors()
        self._actions.load(self.actions)
        self._automations.load(self.automations)
        self.warn_missing_linked_sensors()

        self._gpio_inputs.setup_pins(self._automations.get_gpio_input_edges())
        self._sensors.setup_pins()

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

    def get_sensor_inputs_settings(self):
        return [item for item in self.rpi_inputs if item["input_type"] == InputType.TEMPERATURE_SENSOR.value]

    def get_gpio_inputs_settings(self):
        return [item for item in self.rpi_inputs if item["input_type"] == InputType.GPIO.value]

    def get_sensor_inputs(self):
        return [sensor.config for sensor in self._sensors.get_all().values()]

    def warn_missing_linked_sensors(self):
        sensor_ids = set(self._sensors.get_all())
        for thermostat_output in self._outputs.get_all(ThermostatOutput):
            config = thermostat_output.config
            if config.linked_temp_sensor not in sensor_ids:
                self._logger.warning(
                    "Output %s is linked to sensor %s, which doesn't exist",
                    config.index_id,
                    config.linked_temp_sensor,
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

    def check_enclosure_temp(self):
        """Read every sensor now, then take the decisions on the readings."""
        self._sensor_poller.read_all()
        self._control_loop.evaluate()

    def handle_sensor_reading(self, index_id, outcome):
        try:
            sensor = self._sensors.get(index_id)
        except LookupError:
            return

        if outcome.error is not None:
            self.handle_sensor_failure(sensor.config, outcome.error)
        else:
            self.handle_sensor_recovery(sensor.config)
            with contextlib.suppress(LookupError):
                reading = self._sensor_poller.get_reading(index_id)
                temperature_unit = self._enclosure_settings.temperature_unit
                temperature = (
                    None if reading.temperature is None else temperature_unit.from_celsius(reading.temperature)
                )
                self._mqtt.publish_sensor_reading(sensor.config.label, temperature, reading.humidity)

        self._frontend.update_readings()
        self._control_loop.evaluate_reading(index_id)

    def handle_sensor_failure(self, sensor, error):
        if sensor.index_id in self.failing_sensors:
            self._logger.debug("Sensor %s still can't be read: %s", sensor.label, error)
            return

        self.failing_sensors.add(sensor.index_id)
        self._logger.error(
            "Sensor %s can't be read: %s",
            sensor.label,
            error,
            exc_info=not isinstance(error, SensorError),
        )

        for rule in self._automations.get_all(RuleAutomation):
            trigger = rule.trigger
            if isinstance(trigger, TemperatureTrigger) and trigger.config.linked_temp_sensor == sensor.index_id:
                self._notifications.send(
                    NotificationType.TEMPERATURE_ACTION,
                    f"Temperature alarm: sensor {sensor.label} can't be read",
                )

    def handle_sensor_recovery(self, sensor):
        if sensor.index_id in self.failing_sensors:
            self.failing_sensors.remove(sensor.index_id)
            self._logger.info("Sensor %s has started working again", sensor.label)

    def handle_gpio_input(self, input_id, level):
        self._control_loop.evaluate_gpio_input_edge(input_id, level)

    def handle_temperature_command(self, index_id, temperature, wait):
        self._control_loop.set_thermostat_target(index_id, temperature)
        if wait and self._printer.is_printing():
            self._printer.pause_print()
            self._control_loop.wait_for_temperature(index_id)

    def set_automation_enabled(self, index_id, enabled):
        if not self._enclosure_settings.set_automation_enabled(index_id, enabled=enabled):
            return False

        self.automations = self._enclosure_settings.automations
        with contextlib.suppress(AutomationError):
            self._automations.get(index_id, Automation).enabled = enabled
        self._logger.info("Setting automation %s enabled to %s", index_id, enabled)
        self._control_loop.evaluate()
        self._frontend.update_automations()
        return True

    # ~~ EventPlugin mixin
    def on_event(self, event, payload):
        self._control_loop.evaluate_octoprint_event(event)

        if event == Events.PRINT_DONE:
            file_name = Path(payload["path"]).name
            elapsed_time = octoprint.util.get_formatted_timedelta(timedelta(seconds=payload["time"]))
            self._notifications.send(
                NotificationType.PRINT_FINISH,
                f"Print job finished: {file_name} printed in {elapsed_time}",
            )

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

        # Release the pins of the inputs
        self._gpio_inputs.clear()
        self._sensors.clear()

        # Update the sensor poller
        self._sensor_poller.load(self.get_sensor_inputs_settings())

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

        # Reload the GPIO inputs and set up the pins of the inputs
        self._gpio_inputs.load(self.get_gpio_inputs_settings())
        self._gpio_inputs.setup_pins(self._automations.get_gpio_input_edges())
        self._sensors.setup_pins()

        # Take the decisions again on the new settings
        self._control_loop.evaluate_settings()

        # Update UI in every client
        self._control_loop.update_ui()

    def get_settings_defaults(self):
        return {
            "rpi_inputs": [],
            "rpi_outputs": [],
            "actions": [],
            "automations": [],
            "temperature_unit": "celsius",
            "gcode_control": False,
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
            "gpio_numbering_is_board": gpio_import_error is None and self._gpio.getmode() == self._gpio.BOARD,
            "octoprint_events": sorted(all_events()),
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
        readings = self._sensor_poller.get_readings()
        for sensor in self.get_sensor_inputs():
            reading = readings.get(sensor.index_id)
            if reading is None:
                continue
            if sensor.show_graph_temp and reading.temperature is not None:
                parsed_temps[sensor.label] = (reading.temperature, None)
            if sensor.show_graph_humidity and reading.humidity is not None:
                parsed_temps[sensor.label + " Humidity"] = (reading.humidity, None)

        return parsed_temps
