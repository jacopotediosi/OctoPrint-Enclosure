from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import MeasurementType

if TYPE_CHECKING:
    from collections.abc import Mapping

    from octoprint.plugin.core import PluginManager
    from typing_extensions import Literal

    from octoprint_enclosure.inputs import Reading
    from octoprint_enclosure.outputs import Thermostat
    from octoprint_enclosure.settings import Settings


class Frontend:
    """The plugin's frontend, as a recipient of live updates."""

    def __init__(self, plugin_manager: PluginManager, plugin_identifier: str, settings: Settings) -> None:
        """Set up the channel the frontend live updates are pushed through.

        Args:
            plugin_manager (PluginManager): The OctoPrint plugin manager.
            plugin_identifier (str): The identifier the messages are sent under.
            settings (Settings): The plugin settings.

        """
        self._plugin_manager = plugin_manager
        self._plugin_identifier = plugin_identifier
        self._settings = settings

    def update_readings(self, readings: Mapping[int, Reading]) -> None:
        """Update the latest readings of the inputs with a temperature sensor, by the id of the input."""
        temperature_unit = self._settings.temperature_unit
        sensor_data = [
            {
                "index_id": index_id,
                "temperature": None
                if reading.temperature is None
                else temperature_unit.from_celsius(reading.temperature),
                "humidity": reading.humidity,
                "airquality": reading.airquality,
            }
            for index_id, reading in readings.items()
        ]
        self._send({"sensor_data": sensor_data})

    def update_targets(self, thermostats: Mapping[int, Thermostat]) -> None:
        """Update the targets of the thermostats, by the id of their output."""
        temperature_unit = self._settings.temperature_unit
        set_temperature = []
        for index_id, thermostat in thermostats.items():
            # 0 is the thermostat off, in every unit
            target = thermostat.target
            if target != 0 and thermostat.config.temp_ctr_type.measurement_type is MeasurementType.TEMPERATURE:
                target = temperature_unit.from_celsius(target)
            set_temperature.append({"index_id": index_id, "set_temperature": target})
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

    def update_automations(self, automations: list[dict]) -> None:
        """Update whether each automation is enabled."""
        self._send({"automation_status": automations})

    def show_message(self, message: str, message_type: Literal["success", "error"]) -> None:
        """Show a popup message."""
        self._send({"is_msg": True, "msg": message, "msg_type": message_type})

    def _send(self, data: dict) -> None:
        self._plugin_manager.send_plugin_message(self._plugin_identifier, data)
