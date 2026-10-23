from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Sensor, SensorError
from .dummy import DummySensor
from .registry import SENSORS

if TYPE_CHECKING:
    import logging
    from collections.abc import Iterable

    from .base import Reading

_SensorT = TypeVar("_SensorT", bound=Sensor)


@dataclass(frozen=True)
class SensorInputConfig(BaseConfig):
    """The configuration shared by all the inputs with a temperature sensor."""

    index_id: int
    """The id of the input."""

    temp_sensor_type: str = ""
    """The type of the sensor."""


class _InvalidSensor(Sensor[BaseConfig]):
    """A sensor that can't be set up."""

    config_class = BaseConfig

    _reason: str
    """Why the sensor can't be set up."""

    def __init__(self, reason: str, logger: logging.Logger) -> None:
        super().__init__(BaseConfig(), logger)
        self._reason = reason

    @override
    def read(self) -> Reading:
        raise SensorError(self._reason)


class Sensors:
    """The temperature sensors of the inputs."""

    _logger: logging.Logger

    _dummy: bool
    """Whether every sensor is replaced by the dummy sensor."""

    _sensors: dict[int, Sensor]
    """The sensor of each input, by the id of the input."""

    _lock: threading.Lock
    """Held while the sensors are replaced, and while one is picked to be read."""

    def __init__(self, logger: logging.Logger, *, dummy: bool) -> None:
        """Set up the sensors of the inputs, with none until some settings are loaded.

        Args:
            logger (logging.Logger): The logger to write to.
            dummy (bool): Whether every sensor is replaced by the dummy sensor.

        """
        self._logger = logger.getChild("Sensors")
        self._dummy = dummy
        self._sensors = {}
        self._lock = threading.Lock()

    def load(self, sensor_inputs_settings: Iterable[dict]) -> None:
        """Load the sensors of some inputs from their settings.

        An input whose settings didn't change keeps its sensor as it is, with its state.

        Args:
            sensor_inputs_settings (Iterable[dict]): The settings of the inputs with a temperature sensor.

        """
        sensors: dict[int, Sensor] = {}

        for sensor_input_settings in sensor_inputs_settings:
            try:
                sensor_input_config = SensorInputConfig.from_settings(sensor_input_settings)
            except ValueError as error:
                self._logger.warning("Invalid settings for an input with a temperature sensor: %s", error)
                continue

            sensor_class = DummySensor if self._dummy else SENSORS.get(sensor_input_config.temp_sensor_type)
            if sensor_class is None:
                sensor: Sensor = self._create_invalid_sensor(
                    sensor_input_config.index_id,
                    f"Unsupported sensor type: {sensor_input_config.temp_sensor_type!r}",
                )
            else:
                sensor = self._create_sensor(sensor_class, sensor_input_config.index_id, sensor_input_settings)

            sensors[sensor_input_config.index_id] = sensor

        with self._lock:
            self._sensors = sensors

    def read(self, index_id: int) -> Reading:
        """Read the sensor of an input.

        Args:
            index_id (int): The id of the input.

        Returns:
            Reading: The values read.

        Raises:
            Exception: If the sensor can't be read.

        """
        with self._lock:
            sensor = self._sensors.get(index_id)
        if sensor is None:
            msg = "The sensor is not set up"
            raise SensorError(msg)

        reading = sensor.read()
        self._get_sensor_logger(type(sensor), index_id).debug("Read: %s", reading)
        return reading

    def get_dummy(self, index_id: int) -> DummySensor:
        """Get the dummy sensor of an input.

        Args:
            index_id (int): The id of the input.

        Returns:
            DummySensor: The dummy sensor of the input.

        Raises:
            LookupError: If the input has no dummy sensor.

        """
        with self._lock:
            sensor = self._sensors.get(index_id)
        if isinstance(sensor, DummySensor):
            return sensor

        msg = f"Input {index_id} has no dummy sensor"
        raise LookupError(msg)

    def _create_sensor(
        self,
        sensor_class: type[_SensorT],
        index_id: int,
        input_settings: dict,
    ) -> _SensorT | _InvalidSensor:
        try:
            sensor_config = sensor_class.config_class.from_settings(input_settings)
        except ValueError as error:
            return self._create_invalid_sensor(index_id, f"Invalid settings: {error}")

        # An input whose settings didn't change keeps its sensor, with its state
        sensor = self._sensors.get(index_id)
        if isinstance(sensor, sensor_class) and sensor.config == sensor_config:
            return sensor

        return sensor_class(sensor_config, self._get_sensor_logger(sensor_class, index_id))

    def _create_invalid_sensor(self, index_id: int, reason: str) -> _InvalidSensor:
        logger = self._get_sensor_logger(_InvalidSensor, index_id)
        logger.warning("%s", reason)
        return _InvalidSensor(reason, logger)

    def _get_sensor_logger(self, sensor_class: type[Sensor], index_id: int) -> logging.Logger:
        return self._logger.getChild(f"{sensor_class.__name__}.{index_id}")
