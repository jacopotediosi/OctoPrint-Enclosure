from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import octoprint.plugin
import smbus2
from octoprint.events import all_events
from octoprint.logging.handlers import CleaningTimedRotatingFileHandler
from typing_extensions import override

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

if TYPE_CHECKING:
    from flask import Blueprint
    from octoprint.plugin import PluginSettings
    from octoprint.plugin.core import PluginManager
    from octoprint.printer import PrinterInterface

    from .hardware import GpioBackend, I2cBackend


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

    # Injected by OctoPrint before initialize() runs
    _identifier: str
    _basefolder: str
    _plugin_version: str
    _logger: logging.Logger
    _settings: PluginSettings
    _plugin_manager: PluginManager
    _printer: PrinterInterface

    # Set by initialize()
    _enclosure_settings: Settings
    _development_mode: bool
    _plugin_context: PluginContext
    _gpio_import_error: Exception | None
    _gpio: GpioBackend
    _i2c: I2cBackend
    _sensors: Sensors
    _sensor_poller: SensorPoller
    _gpio_inputs: GpioInputs
    _outputs: Outputs
    _actions: Actions
    _automations: Automations
    _api: Api
    _frontend: Frontend
    _control_loop: ControlLoop
    _scheduler: Scheduler
    _output_executor: OutputExecutor
    _enc_handler: EncHandler
    _encdev_handler: EncDevHandler
    _notifications: Notifications
    _mqtt: Mqtt

    ##########
    ### Initialization
    ##########

    @override
    def initialize(self) -> None:
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
        self._gpio_import_error = gpio.get_import_error()
        if self._development_mode:
            self._gpio = dummy_gpio
            self._i2c = dummy_i2c
            self._logger.warning("Development mode is enabled: GPIO and I2C (pins, sensors, etc) are simulated")
        else:
            self._gpio = gpio
            self._i2c = smbus2
            if self._gpio_import_error is not None:
                self._logger.error("The GPIO library can't be imported: %s", self._gpio_import_error)

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

    @override
    def get_assets(self) -> dict:
        return {
            "js": ["js/enclosure.js"],
            "css": ["css/enclosure.css"],
        }

    ##########
    ### BlueprintPlugin mixin
    ##########

    @override
    def is_blueprint_protected(self) -> bool:
        return False

    @override
    def is_blueprint_csrf_protected(self) -> bool:
        return True

    @override
    def get_blueprint(self) -> Blueprint:
        return self._api.get_blueprint()

    ##########
    ### EventHandlerPlugin mixin
    ##########

    @override
    def on_event(self, event: str, payload: dict | None) -> None:
        self._control_loop.evaluate_octoprint_event(event, payload)

    ##########
    ### SettingsPlugin mixin
    ##########

    @override
    def get_settings_defaults(self) -> dict:
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

    @override
    def get_settings_restricted_paths(self) -> dict:
        return {"admin": [["notification_api_key"]]}

    @override
    def get_settings_version(self) -> int:
        return 11

    @override
    def on_settings_migrate(self, target: int, current: int | None = None) -> None:
        migrate_settings(target, current, self._settings, self._logger)

    @override
    def on_settings_save(self, data: dict) -> None:
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

    @override
    def on_shutdown(self) -> None:
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

    @override
    def on_after_startup(self) -> None:
        self._mqtt.load_helpers()

        self._apply_settings()

        self._sensor_poller.start(self._control_loop.evaluate_reading, self._control_loop.evaluate_sensor_failure)
        self._control_loop.start()

    ##########
    ### TemplatePlugin mixin
    ##########

    @override
    def get_template_configs(self) -> list[dict]:
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

    @override
    def get_template_vars(self) -> dict:
        gpio_import_error = self._gpio_import_error
        return {
            "development_mode": self._development_mode,
            "gpio_import_error": str(gpio_import_error) if gpio_import_error is not None else None,
            "gpio_numbering_is_board": gpio_import_error is None and self._gpio.getmode() == self._gpio.BOARD,
            "octoprint_events": sorted(all_events()),
        }

    @override
    def is_template_autoescaped(self) -> bool:
        return True

    ##########
    ### Hooks
    ##########

    def hook_access_permissions(self) -> list[dict]:
        """Tell OctoPrint the permissions of the plugin.

        Returns:
            list[dict]: The permissions of the plugin.

        """
        return get_additional_permissions()

    def hook_atcommand_queuing(
        self,
        _comm_instance: Any,  # noqa: ANN401 - connection type varies across OctoPrint versions
        _phase: str,
        command: str,
        parameters: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        """Run an @ command queued for the printer.

        Args:
            _comm_instance (Any): The connection to the printer.
            _phase (str): The phase of the queue the command is in.
            command (str): The name of the @ command, without the @.
            parameters (str): The parameters of the @ command.
            *_args: Further positional arguments OctoPrint may pass.
            **_kwargs: Further keyword arguments OctoPrint may pass.

        """
        self._encdev_handler.handle(command, parameters)

    def hook_gcode_queuing(
        self,
        _comm_instance: Any,  # noqa: ANN401 - connection type varies across OctoPrint versions
        _phase: str,
        cmd: str,
        _cmd_type: str | None,
        _gcode: str | None,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        """Run a G-code line queued for the printer.

        Args:
            _comm_instance (Any): The connection to the printer.
            _phase (str): The phase of the queue the line is in.
            cmd (str): The G-code line.
            _cmd_type (str | None): The type of the line, or None if it has none.
            _gcode (str | None): The G-code of the line, e.g. "M105", or None if it has none.
            *_args: Further positional arguments OctoPrint may pass.
            **_kwargs: Further keyword arguments OctoPrint may pass.

        """
        self._enc_handler.handle(cmd)

    def hook_temperatures_received(
        self,
        _comm_instance: Any,  # noqa: ANN401 - connection type varies across OctoPrint versions
        parsed_temperatures: dict,
        *_args: Any,
        **_kwargs: Any,
    ) -> dict:
        """Add the readings of the sensors to the temperatures OctoPrint shows in its graph.

        Args:
            _comm_instance (Any): The connection to the printer.
            parsed_temperatures (dict): The temperatures to report, by name.
            *_args: Further positional arguments OctoPrint may pass.
            **_kwargs: Further keyword arguments OctoPrint may pass.

        Returns:
            dict: The temperatures to report, with the readings of the sensors shown in the graph.

        """
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

    def hook_softwareupdate_check_config(self) -> dict:
        """Tell the Software Update plugin where to look for new releases.

        Returns:
            dict: The update configuration, by plugin identifier.

        """
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
        outputs_settings = self._enclosure_settings.rpi_outputs
        actions_settings = self._enclosure_settings.actions
        automations_settings = self._enclosure_settings.automations
        self._sensor_poller.load(inputs_settings)
        self._gpio_inputs.load(inputs_settings)
        self._output_executor.load_outputs(outputs_settings, wait=True)
        self._actions.load(actions_settings)
        self._automations.load(automations_settings)

        # Check the links of the automations to the other entries
        self._automations.check_links(self._sensors, self._gpio_inputs, self._outputs, self._actions)

        # Set up the pins of the inputs
        self._gpio_inputs.setup_pins(
            self._automations.get_gpio_input_edges(),
            self._control_loop.evaluate_gpio_input_edge,
        )
        self._sensors.setup_pins()

        self._logger.info(
            "Settings applied: %s inputs, %s outputs, %s actions, %s automations",
            len(inputs_settings),
            len(outputs_settings),
            len(actions_settings),
            len(automations_settings),
        )
