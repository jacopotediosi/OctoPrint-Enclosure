from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from octoprint.plugin.core import PluginManager

PLUGIN_ID = "mqtt"
ROOT_TOPIC = "octoprint/plugins/enclosure"


class Mqtt:
    """The MQTT broker the MQTT plugin is connected to."""

    def __init__(self, plugin_manager: PluginManager, logger: logging.Logger) -> None:
        """Set up the publishing through the MQTT plugin.

        Args:
            plugin_manager (PluginManager): The OctoPrint plugin manager.
            logger (logging.Logger): The logger to write to.

        """
        self._plugin_manager = plugin_manager
        self._logger = logger.getChild("Mqtt")
        self._mqtt_publish = None

    def load_helpers(self) -> None:
        """Look up the helpers of the MQTT plugin."""
        helpers = self._plugin_manager.get_helpers(PLUGIN_ID, "mqtt_publish")

        if helpers and "mqtt_publish" in helpers:
            self._mqtt_publish = helpers["mqtt_publish"]
        else:
            self._logger.warning("Mqtt helpers not found. Mqtt integration won't work.")

    def publish_sensor_reading(self, sensor_label: str, temperature: float, humidity: float) -> None:
        """Publish the latest reading of a temperature sensor."""
        if self._mqtt_publish is None:
            return

        self._mqtt_publish(f"{ROOT_TOPIC}/{sensor_label}", {"temperature": temperature, "humidity": humidity})
