import logging
import sys

import octoprint.plugin
import smbus2
from octoprint.events import all_events
from octoprint.logging.handlers import CleaningTimedRotatingFileHandler

from .actions import Actions
from .api import Api
from .automations import Automations
from .engine import ControlLoop, OutputExecutor, Scheduler
from .frontend import Frontend
from .gcode_commands import EncDevHandler, EncHandler
from .hardware import dummy_gpio, dummy_i2c, gpio
from .inputs import GpioInputs, SensorPoller, Sensors
from .integrations import Mqtt
from .notifications import Notifications, NotificationType
from .outputs import Outputs
from .permissions import get_additional_permissions
from .plugin_context import PluginContext
from .settings import Settings
from .settings.migrations import migrate_settings


class EnclosurePlugin(
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.BlueprintPlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.TemplatePlugin,
):
    """The OctoPrint plugin that monitors and controls a printer enclosure."""

    ##########
    ### Initialization
    ##########

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

        # Init the settings
        self._enclosure_settings = Settings(self._settings)

        # Init hardware
        self._development_mode = self._enclosure_settings.development_mode
        if self._development_mode:
            self._gpio = dummy_gpio
            self._i2c = dummy_i2c
            self._logger.warning("Development mode is enabled: GPIO and I2C (pins, sensors, etc) are simulated")
        else:
            self._gpio = gpio
            self._i2c = smbus2

        # Init inputs, outputs, automations, frontend and actions
        self._sensors = Sensors(self._gpio, self._logger, dummy=self._development_mode)
        self._sensor_poller = SensorPoller(self._sensors, self._logger)
        self._gpio_inputs = GpioInputs(self._gpio, self._logger)
        self._outputs = Outputs(self._gpio, self._i2c, self._sensors, self._logger)
        self._automations = Automations(self._logger)
        self._frontend = Frontend(
            self._plugin_manager,
            self._identifier,
            self._sensors,
            self._gpio_inputs,
            self._sensor_poller,
            self._outputs,
            self._automations,
            self._logger,
        )
        self._actions = Actions(self._printer, self._frontend, self._logger)

        # Init notifications
        self._notifications = Notifications(self._enclosure_settings, self._logger)

        # Init integrations
        self._mqtt = Mqtt(self._plugin_manager, self._logger)

        # Init the engine
        self._scheduler = Scheduler(self._logger)
        self._output_executor = OutputExecutor(self._outputs, self._frontend, self._logger)
        self._control_loop = ControlLoop(
            self._sensors,
            self._gpio_inputs,
            self._sensor_poller,
            self._outputs,
            self._actions,
            self._automations,
            self._output_executor,
            self._scheduler,
            self._notifications,
            self._mqtt,
            self._printer,
            self._frontend,
            self._enclosure_settings,
            self._logger,
        )

        # Init the plugin context
        self._plugin_context = PluginContext(
            identifier=self._identifier,
            basefolder=self._basefolder,
            development_mode=self._development_mode,
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
        self._enc_handler = EncHandler(self._plugin_context)
        self._encdev_handler = EncDevHandler(self._plugin_context)

        # Init API
        self._api = Api(self._plugin_context)

    ##########
    ### AssetPlugin mixin
    ##########

    def get_assets(self):
        return {
            "js": ["js/enclosure.js"],
            "css": ["css/enclosure.css"],
        }

    ##########
    ### BlueprintPlugin mixin
    ##########

    def is_blueprint_protected(self):
        return False

    def is_blueprint_csrf_protected(self):
        return True

    def get_blueprint(self):
        return self._api.get_blueprint()

    ##########
    ### EventHandlerPlugin mixin
    ##########

    def on_event(self, event, payload):
        self._control_loop.evaluate_octoprint_event(event, payload)

    ##########
    ### SettingsPlugin mixin
    ##########

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

    def get_settings_restricted_paths(self):
        return {"admin": [["notification_api_key"]]}

    def get_settings_version(self):
        return 11

    def on_settings_migrate(self, target, current=None):
        migrate_settings(target, current, self._settings, self._logger)

    def on_settings_save(self, data):
        # Save the settings
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

        # Apply the saved settings
        self._apply_settings()

        # Take the decisions again on the new settings
        self._control_loop.evaluate_new_settings()

        # Update UI in every client
        self._control_loop.update_ui()

    ##########
    ### ShutdownPlugin mixin
    ##########

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

    ##########
    ### StartupPlugin mixin
    ##########

    def on_after_startup(self):
        self._mqtt.load_helpers()

        self._apply_settings()

        self._sensor_poller.start(self._control_loop.evaluate_reading, self._control_loop.evaluate_sensor_failure)
        self._control_loop.start()

    ##########
    ### TemplatePlugin mixin
    ##########

    def get_template_configs(self):
        return [
            {"type": "settings", "custom_bindings": True},
            {
                "type": "tab",
                "custom_bindings": True,
                "styles": ["display: none;"],
                "data_bind": "visible: hasStatusPermission",
            },
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

    def get_template_vars(self):
        gpio_import_error = gpio.get_import_error()
        return {
            "development_mode": self._development_mode,
            "gpio_import_error": str(gpio_import_error) if gpio_import_error is not None else None,
            "gpio_numbering_is_board": gpio_import_error is None and self._gpio.getmode() == self._gpio.BOARD,
            "octoprint_events": sorted(all_events()),
        }

    def is_template_autoescaped(self):
        return True

    ##########
    ### Hooks
    ##########

    def hook_access_permissions(self):
        return get_additional_permissions()

    def hook_atcommand_queuing(self, comm_instance, phase, command, parameters, tags=None, *args, **kwargs):
        self._encdev_handler.handle(comm_instance, command, parameters)

    def hook_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, *args, **kwargs):
        self._enc_handler.handle(comm_instance, cmd)

    def hook_temperatures_received(self, comm_instance, parsed_temperatures, *args, **kwargs):
        readings = self._sensor_poller.get_readings()
        for sensor in self._sensors.get_all().values():
            config = sensor.config
            reading = readings.get(config.index_id)
            if reading is None:
                continue
            if config.show_graph_temp and reading.temperature is not None:
                parsed_temperatures[config.label] = (reading.temperature, None)
            if config.show_graph_humidity and reading.humidity is not None:
                parsed_temperatures[config.label + " Humidity"] = (reading.humidity, None)

        return parsed_temperatures

    def hook_softwareupdate_check_config(self):
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

    ##########
    ### Helpers
    ##########

    def _apply_settings(self) -> None:
        # Release the pins of the inputs
        self._gpio_inputs.clear()
        self._sensors.clear()

        # Load the inputs, the outputs, the actions and the automations
        inputs_settings = self._enclosure_settings.rpi_inputs
        self._sensor_poller.load(inputs_settings)
        self._gpio_inputs.load(inputs_settings)
        self._output_executor.load_outputs(self._enclosure_settings.rpi_outputs, wait=True)
        self._actions.load(self._enclosure_settings.actions)
        self._automations.load(self._enclosure_settings.automations)

        # Check the links of the automations to the other entries
        self._automations.check_links(self._sensors, self._gpio_inputs, self._outputs, self._actions)

        # Set up the pins of the inputs
        self._gpio_inputs.setup_pins(
            self._automations.get_gpio_input_edges(),
            self._control_loop.evaluate_gpio_input_edge,
        )
        self._sensors.setup_pins()
