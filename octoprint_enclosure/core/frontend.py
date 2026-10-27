from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from octoprint.plugin.core import PluginManager
    from typing_extensions import Literal


class Frontend:
    """The plugin's frontend, as a recipient of live updates."""

    def __init__(self, plugin_manager: PluginManager, plugin_identifier: str) -> None:
        """Set up the channel the frontend live updates are pushed through.

        Args:
            plugin_manager (PluginManager): The OctoPrint plugin manager.
            plugin_identifier (str): The identifier the messages are sent under.

        """
        self._plugin_manager = plugin_manager
        self._plugin_identifier = plugin_identifier

    def update_readings(self, sensor_data: list[dict]) -> None:
        """Update the latest readings of the temperature sensors."""
        self._send({"sensor_data": sensor_data})

    def update_targets(self, targets: dict[int, float]) -> None:
        """Update the targets of the thermostats, by the id of their output."""
        set_temperature = [{"index_id": index_id, "set_temperature": target} for index_id, target in targets.items()]
        self._send({"set_temperature": set_temperature})

    def update_outputs(
        self,
        regular: list[dict],
        pwm: list[dict],
        neopixel: list[dict],
        ledstrip: list[dict],
        thermostats: list[dict],
    ) -> None:
        """Update the state of the outputs, grouped by output type."""
        self._send(
            {
                "rpi_output_regular": regular,
                "rpi_output_pwm": pwm,
                "rpi_output_neopixel": neopixel,
                "rpi_output_ledstrip": ledstrip,
                "rpi_output_thermostat": thermostats,
            },
        )

    def update_filament_sensors(self, filament_sensors: list[dict]) -> None:
        """Update whether each filament sensor is enabled."""
        self._send({"filament_sensor_status": filament_sensors})

    def show_message(self, message: str, message_type: Literal["success", "error"]) -> None:
        """Show a popup message."""
        self._send({"is_msg": True, "msg": message, "msg_type": message_type})

    def _send(self, data: dict) -> None:
        self._plugin_manager.send_plugin_message(self._plugin_identifier, data)
