from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.automations import Automation
from octoprint_enclosure.outputs import (
    LedstripOutput,
    NeopixelDirectOutput,
    NeopixelIndirectOutput,
    Output,
    OutputError,
    OutputType,
    PwmOutput,
)
from octoprint_enclosure.utils import MeasurementType

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping

    from octoprint.plugin.core import PluginManager
    from typing_extensions import Literal

    from octoprint_enclosure.automations import Automations
    from octoprint_enclosure.inputs import SensorPoller
    from octoprint_enclosure.outputs import Outputs, Thermostat
    from octoprint_enclosure.settings import Settings


class Frontend:
    """The plugin's frontend handler."""

    _plugin_manager: PluginManager
    _plugin_identifier: str
    _settings: Settings
    _outputs: Outputs
    _automations: Automations
    _sensor_poller: SensorPoller
    _logger: logging.Logger

    def __init__(
        self,
        plugin_manager: PluginManager,
        plugin_identifier: str,
        settings: Settings,
        outputs: Outputs,
        automations: Automations,
        sensor_poller: SensorPoller,
        logger: logging.Logger,
    ) -> None:
        """Set up the channel the frontend live updates are pushed through.

        Args:
            plugin_manager (PluginManager): The OctoPrint plugin manager.
            plugin_identifier (str): The identifier the messages are sent under.
            settings (Settings): The plugin settings.
            outputs (Outputs): The outputs.
            automations (Automations): The automations.
            sensor_poller (SensorPoller): The poller of the temperature sensors.
            logger (logging.Logger): The logger to write to.

        """
        self._plugin_manager = plugin_manager
        self._plugin_identifier = plugin_identifier
        self._settings = settings
        self._outputs = outputs
        self._automations = automations
        self._sensor_poller = sensor_poller
        self._logger = logger.getChild("Frontend")

    def update_readings(self) -> None:
        """Update the latest readings of the inputs with a temperature sensor."""
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
            for index_id, reading in self._sensor_poller.get_readings().items()
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

    def update_outputs(self) -> None:
        """Update the state of the outputs, grouped by output type."""
        # The group of the push and the field with the state, for each type of output shown in the frontend
        output_pushes = {
            OutputType.REGULAR: ("rpi_output_regular", "status"),
            OutputType.PWM: ("rpi_output_pwm", "pwm_value"),
            OutputType.NEOPIXEL_DIRECT: ("rpi_output_neopixel", "color"),
            OutputType.NEOPIXEL_INDIRECT: ("rpi_output_neopixel", "color"),
            OutputType.LEDSTRIP: ("rpi_output_ledstrip", "color"),
            OutputType.THERMOSTAT: ("rpi_output_thermostat", "status"),
        }
        output_groups: dict[str, list[dict]] = {group: [] for group, _ in output_pushes.values()}

        for output in self._outputs.get_all(Output):
            if output.config.output_type not in output_pushes:
                continue

            index_id = output.config.index_id
            group, field = output_pushes[output.config.output_type]
            value: bool | int | str
            if field == "status":
                try:
                    value = output.is_on()
                except OutputError:
                    value = False
                except Exception:
                    self._logger.exception("Error reading output %s", index_id)
                    value = False
            elif field == "pwm_value":
                if not isinstance(output, PwmOutput):
                    continue
                value = int(output.duty_cycle)
            else:
                color = None
                if isinstance(output, (LedstripOutput, NeopixelDirectOutput, NeopixelIndirectOutput)):
                    color = output.color
                red, green, blue = (0, 0, 0) if color is None else color
                value = f"rgb({red},{green},{blue})"
            output_groups[group].append({"index_id": index_id, field: value})

        self._send(output_groups)

    def update_automations(self) -> None:
        """Update whether each automation is enabled."""
        automation_status = [
            {"index_id": automation.config.index_id, "enabled": automation.enabled}
            for automation in self._automations.get_all(Automation, include_disabled=True)
        ]
        self._send({"automation_status": automation_status})

    def show_message(self, message: str, message_type: Literal["success", "error"]) -> None:
        """Show a popup message."""
        self._send({"is_msg": True, "msg": message, "msg_type": message_type})

    def _send(self, data: dict) -> None:
        try:
            self._plugin_manager.send_plugin_message(self._plugin_identifier, data)
        except Exception:
            self._logger.exception("Error sending a message to the UI")
