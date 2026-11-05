from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from octoprint_enclosure.utils import to_int

from .measurement import TemperatureUnit

if TYPE_CHECKING:
    from octoprint.plugin import PluginSettings


class Settings:
    """The plugin settings."""

    def __init__(self, settings: PluginSettings) -> None:
        """Set up the access to the plugin settings.

        Args:
            settings (PluginSettings): The OctoPrint settings accessor of this plugin.

        """
        self._settings = settings
        self.write_lock = threading.RLock()

    def save(self) -> None:
        """Write the settings changed so far to disk."""
        with self.write_lock:
            self._settings.save()

    ##########
    ### Inputs
    ##########

    @property
    def rpi_inputs(self) -> list[dict]:
        """The configured inputs."""
        return self._settings.get(["rpi_inputs"])

    @rpi_inputs.setter
    def rpi_inputs(self, value: list[dict]) -> None:
        with self.write_lock:
            self._settings.set(["rpi_inputs"], value)

    ##########
    ### Outputs
    ##########

    @property
    def rpi_outputs(self) -> list[dict]:
        """The configured outputs."""
        return self._settings.get(["rpi_outputs"])

    @rpi_outputs.setter
    def rpi_outputs(self, value: list[dict]) -> None:
        with self.write_lock:
            self._settings.set(["rpi_outputs"], value)

    ##########
    ### Actions
    ##########

    @property
    def actions(self) -> list[dict]:
        """The configured actions, such as G-code and shell scripts."""
        return self._settings.get(["actions"])

    ##########
    ### Automations
    ##########

    @property
    def automations(self) -> list[dict]:
        """The configured automations."""
        return self._settings.get(["automations"])

    @automations.setter
    def automations(self, value: list[dict]) -> None:
        with self.write_lock:
            self._settings.set(["automations"], value)

    def set_automation_enabled(self, index_id: int, *, enabled: bool) -> bool:
        """Enable or disable an automation, and write it to disk.

        Args:
            index_id (int): The id of the automation.
            enabled (bool): Whether the automation is enabled.

        Returns:
            bool: Whether an automation has that id.

        """
        with self.write_lock:
            automations = self.automations
            automation = next((item for item in automations if to_int(item.get("index_id")) == index_id), None)
            if automation is None:
                return False
            automation["enabled"] = enabled
            self.automations = automations
            self.save()
        return True

    ##########
    ### Temperatures
    ##########

    @property
    def temperature_unit(self) -> TemperatureUnit:
        """The unit the temperatures are shown and entered in."""
        try:
            return TemperatureUnit(self._settings.get(["temperature_unit"]))
        except ValueError:
            return TemperatureUnit.CELSIUS

    ##########
    ### G-code
    ##########

    @property
    def gcode_control(self) -> bool:
        """Whether the outputs can be controlled through the ENC G-code command."""
        return bool(self._settings.get_boolean(["gcode_control"]))

    @property
    def filament_sensor_gcode(self) -> str:
        """The G-code sent to the printer when a filament sensor detects the end of the filament."""
        return self._settings.get(["filament_sensor_gcode"]) or ""

    ##########
    ### Notifications
    ##########

    @property
    def notifications(self) -> list[dict]:
        """Which notifications are enabled."""
        return self._settings.get(["notifications"])

    @property
    def notification_provider(self) -> str:
        """The service the notifications are sent through."""
        return self._settings.get(["notification_provider"]) or ""

    @property
    def notification_api_key(self) -> str:
        """The IFTTT API key."""
        return self._settings.get(["notification_api_key"]) or ""

    @property
    def notification_event_name(self) -> str:
        """The IFTTT event the notifications trigger."""
        return self._settings.get(["notification_event_name"]) or ""

    ##########
    ### Development
    ##########

    @property
    def development_mode(self) -> bool:
        """Whether the plugin runs in development mode."""
        return bool(self._settings.get_boolean(["development_mode"]))
