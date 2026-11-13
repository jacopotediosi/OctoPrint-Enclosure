from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.inputs import GpioInputError, Reading
from octoprint_enclosure.permissions import PluginPermission

from .base import BaseApi
from .responses import ErrorResponse, ItemResponse, error_response, item_response, list_response
from .routes import route

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping

    from flask import Response

    from octoprint_enclosure.inputs import GpioInputs, SensorPoller, Sensors
    from octoprint_enclosure.inputs.gpio.gpio_input import GpioInput
    from octoprint_enclosure.inputs.sensors.base import Sensor
    from octoprint_enclosure.plugin_context import PluginContext


@dataclass(frozen=True)
class InputResponse(ItemResponse):
    """An input, and its state."""

    @classmethod
    def from_inputs(
        cls,
        sensors: Sensors,
        gpio_inputs: GpioInputs,
        readings: Mapping[int, Reading],
        logger: logging.Logger,
    ) -> list[InputResponse]:
        """Describe every input, reading the pins of the GPIO inputs.

        Args:
            sensors (Sensors): The temperature sensors.
            gpio_inputs (GpioInputs): The GPIO inputs.
            readings (Mapping[int, Reading]): The last reading of each sensor, by the id of its input.
            logger (logging.Logger): The logger to write to if a pin can't be read.

        Returns:
            list[InputResponse]: The inputs with their state, each as the response of its type.

        """
        inputs: list[InputResponse] = [
            SensorInputResponse.from_sensor(sensor, readings.get(index_id, Reading()))
            for index_id, sensor in sensors.get_all().items()
        ]
        inputs += [GpioInputResponse.from_gpio_input(gpio_input, logger) for gpio_input in gpio_inputs.get_all()]
        return inputs


@dataclass(frozen=True)
class SensorInputResponse(InputResponse):
    """An input with a temperature sensor, and its last reading."""

    temperature: float | None
    """The temperature in Celsius, or null if the sensor has none."""

    humidity: float | None
    """The relative humidity in percent, or null if the sensor has none."""

    air_quality: float | None
    """The air quality index, or null if the sensor has none."""

    @classmethod
    def from_sensor(cls, sensor: Sensor, reading: Reading) -> SensorInputResponse:
        """Describe an input with a temperature sensor.

        Args:
            sensor (Sensor): The sensor of the input.
            reading (Reading): The last reading of the sensor.

        Returns:
            SensorInputResponse: The input, with its last reading.

        """
        config = sensor.config
        return cls(
            id=config.index_id,
            type=config.input_type.value,
            label=config.label,
            temperature=reading.temperature,
            humidity=reading.humidity,
            air_quality=reading.airquality,
        )


@dataclass(frozen=True)
class GpioInputResponse(InputResponse):
    """An input on a GPIO pin, and its state."""

    active: bool | None
    """Whether the input is active, or null if its pin can't be read."""

    @classmethod
    def from_gpio_input(cls, gpio_input: GpioInput, logger: logging.Logger) -> GpioInputResponse:
        """Describe an input on a GPIO pin, reading its pin.

        Args:
            gpio_input (GpioInput): The input.
            logger (logging.Logger): The logger to write to if the pin can't be read.

        Returns:
            GpioInputResponse: The input, with its state.

        """
        config = gpio_input.config
        try:
            active = gpio_input.is_active()
        except Exception as error:  # noqa: BLE001 - a traceback at every push would fill the log
            logger.debug("Can't read input %s: %s", config.index_id, error)
            active = None
        return cls(id=config.index_id, type=config.input_type.value, label=config.label, active=active)


class InputsApi(BaseApi):
    """The HTTP API of the inputs."""

    _sensors: Sensors
    _gpio_inputs: GpioInputs
    _sensor_poller: SensorPoller

    def __init__(self, plugin_context: PluginContext) -> None:
        """Set up the API.

        Args:
            plugin_context (PluginContext): The plugin context.

        """
        super().__init__(plugin_context)
        self._sensors = plugin_context.sensors
        self._gpio_inputs = plugin_context.gpio_inputs
        self._sensor_poller = plugin_context.sensor_poller

    @route("GET", "/inputs", permission=PluginPermission.STATUS, responses={200: [InputResponse]})
    def get_inputs(self) -> Response:
        """List the inputs, with their state."""
        readings = self._sensor_poller.get_readings()
        return list_response(InputResponse.from_inputs(self._sensors, self._gpio_inputs, readings, self._logger))

    @route(
        "GET",
        "/inputs/<int:input_id>",
        permission=PluginPermission.STATUS,
        responses={200: InputResponse, 404: ErrorResponse},
    )
    def get_input(self, input_id: int) -> Response:
        """Get an input, with its state."""
        try:
            sensor = self._sensors.get(input_id)
        except LookupError:
            pass
        else:
            reading = self._sensor_poller.get_readings().get(input_id, Reading())
            return item_response(SensorInputResponse.from_sensor(sensor, reading))

        try:
            gpio_input = self._gpio_inputs.get(input_id)
        except GpioInputError:
            return error_response(404, f"No input is set up with id {input_id}.")

        return item_response(GpioInputResponse.from_gpio_input(gpio_input, self._logger))
