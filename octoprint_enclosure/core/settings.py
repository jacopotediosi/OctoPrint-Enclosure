from __future__ import annotations

import threading
from typing import TYPE_CHECKING

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

    ##########
    ### RPI inputs and outputs
    ##########

    @property
    def rpi_inputs(self) -> list[dict]:
        """The configured inputs."""
        return self._settings.get(["rpi_inputs"])

    @rpi_inputs.setter
    def rpi_inputs(self, value: list[dict]) -> None:
        with self.write_lock:
            self._settings.set(["rpi_inputs"], value)

    @property
    def rpi_outputs(self) -> list[dict]:
        """The configured outputs."""
        return self._settings.get(["rpi_outputs"])

    @rpi_outputs.setter
    def rpi_outputs(self, value: list[dict]) -> None:
        with self.write_lock:
            self._settings.set(["rpi_outputs"], value)

    ##########
    ### GPIO
    ##########

    @property
    def use_board_pin_number(self) -> bool:
        """Whether GPIO pins are numbered by their position on the board, instead of by their BCM number."""
        return bool(self._settings.get_boolean(["use_board_pin_number"]))

    @use_board_pin_number.setter
    def use_board_pin_number(self, value: bool) -> None:
        with self.write_lock:
            self._settings.set_boolean(["use_board_pin_number"], value)

    ##########
    ### Scripts
    ##########

    @property
    def use_sudo(self) -> bool:
        """Whether the sensor and NeoPixel scripts are run with sudo."""
        return bool(self._settings.get_boolean(["use_sudo"]))

    ##########
    ### NeoPixel
    ##########

    @property
    def neopixel_dma(self) -> int:
        """The DMA channel used to drive the NeoPixels connected directly to the Raspberry Pi."""
        value = self._settings.get_int(["neopixel_dma"])
        return 10 if value is None else value

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
