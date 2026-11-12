from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from octoprint_enclosure.api import AutomationResponse, InputResponse, OutputResponse

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable, Mapping

    from octoprint.plugin.core import PluginManager
    from typing_extensions import Literal

    from octoprint_enclosure.api.responses import ItemResponse
    from octoprint_enclosure.automations import Automations
    from octoprint_enclosure.inputs import GpioInputs, SensorPoller, Sensors
    from octoprint_enclosure.outputs import Outputs, Thermostat


class Frontend:
    """The plugin's frontend handler."""

    _plugin_manager: PluginManager
    _plugin_identifier: str
    _sensors: Sensors
    _gpio_inputs: GpioInputs
    _sensor_poller: SensorPoller
    _outputs: Outputs
    _automations: Automations
    _logger: logging.Logger

    _thermostats: Mapping[int, Thermostat]
    """The thermostats, by the id of their output."""

    def __init__(
        self,
        plugin_manager: PluginManager,
        plugin_identifier: str,
        sensors: Sensors,
        gpio_inputs: GpioInputs,
        sensor_poller: SensorPoller,
        outputs: Outputs,
        automations: Automations,
        logger: logging.Logger,
    ) -> None:
        """Set up the channel the frontend live updates are pushed through.

        Args:
            plugin_manager (PluginManager): The OctoPrint plugin manager.
            plugin_identifier (str): The identifier the messages are sent under.
            sensors (Sensors): The temperature sensors.
            gpio_inputs (GpioInputs): The GPIO inputs.
            sensor_poller (SensorPoller): The poller of the temperature sensors.
            outputs (Outputs): The outputs.
            automations (Automations): The automations.
            logger (logging.Logger): The logger to write to.

        """
        self._plugin_manager = plugin_manager
        self._plugin_identifier = plugin_identifier
        self._sensors = sensors
        self._gpio_inputs = gpio_inputs
        self._sensor_poller = sensor_poller
        self._outputs = outputs
        self._automations = automations
        self._logger = logger.getChild("Frontend")

        self._thermostats = {}

    def set_thermostats(self, thermostats: Mapping[int, Thermostat]) -> None:
        """Set the thermostats the outputs are sent with.

        Args:
            thermostats (Mapping[int, Thermostat]): The thermostats, by the id of their output.

        """
        self._thermostats = thermostats

    def update_inputs(self) -> None:
        """Update the inputs."""
        readings = self._sensor_poller.get_readings()
        inputs = InputResponse.from_inputs(self._sensors, self._gpio_inputs, readings, self._logger)
        self._send_items("inputs", inputs)

    def update_outputs(self) -> None:
        """Update the outputs."""
        outputs = OutputResponse.from_outputs(self._outputs, self._thermostats, self._logger)
        self._send_items("outputs", outputs)

    def update_automations(self) -> None:
        """Update the automations."""
        self._send_items("automations", AutomationResponse.from_automations(self._automations))

    def show_message(self, message: str, message_type: Literal["success", "error"]) -> None:
        """Show a popup message."""
        self._send({"is_msg": True, "msg": message, "msg_type": message_type})

    def _send_items(self, name: str, items: Iterable[ItemResponse]) -> None:
        self._send({name: [asdict(item) for item in sorted(items, key=lambda item: item.id)]})

    def _send(self, data: dict) -> None:
        try:
            self._plugin_manager.send_plugin_message(self._plugin_identifier, data)
        except Exception:
            self._logger.exception("Error sending a message to the UI")
