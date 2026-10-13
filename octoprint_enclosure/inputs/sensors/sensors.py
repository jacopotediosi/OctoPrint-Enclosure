from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from .dummy import DummySensor
from .registry import SENSORS

if TYPE_CHECKING:
    import logging

    from .base import Reading, Sensor

_SensorT = TypeVar("_SensorT", bound="Sensor")


class UnsupportedSensorTypeError(Exception):
    """Raised when the kind of a sensor is not supported."""


class Sensors:
    """The temperature sensors."""

    def __init__(self, logger: logging.Logger, *, dummy: bool) -> None:
        """Set up the reading of the sensors.

        Args:
            logger (logging.Logger): The logger to write to.
            dummy (bool): Whether every sensor is replaced by the dummy sensor.

        """
        self._logger = logger.getChild("Sensors")
        self._dummy = dummy
        self._sensors: dict[int, Sensor] = {}

    def read(self, config: dict) -> Reading:
        """Read a sensor.

        Args:
            config (dict): The configuration of the sensor.

        Returns:
            Reading: The values read.

        Raises:
            UnsupportedSensorTypeError: If the kind of the sensor is not supported.

        """
        if self._dummy:
            return self.get_dummy(config["index_id"]).read()

        sensor_class = SENSORS.get(config["temp_sensor_type"])
        if sensor_class is None:
            msg = f"Unsupported sensor type: {config['temp_sensor_type']}"
            raise UnsupportedSensorTypeError(msg)

        return self._get_sensor(config["index_id"], sensor_class).read()

    def get_dummy(self, index_id: int) -> DummySensor:
        """Get the dummy sensor of an input.

        Args:
            index_id (int): The id of the input.

        Returns:
            DummySensor: The dummy sensor of the input.

        """
        return self._get_sensor(index_id, DummySensor)

    def _get_sensor(self, index_id: int, sensor_class: type[_SensorT]) -> _SensorT:
        sensor = self._sensors.get(index_id)
        if not isinstance(sensor, sensor_class):
            sensor = sensor_class(self._logger)
            self._sensors[index_id] = sensor
        return sensor
