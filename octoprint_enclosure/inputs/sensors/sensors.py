from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from .base import SensorError
from .dummy import DummySensor
from .registry import SENSORS

if TYPE_CHECKING:
    import logging

    from .base import Reading, Sensor

_SensorT = TypeVar("_SensorT", bound="Sensor")


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

    def read(self, settings: dict) -> Reading:
        """Read a sensor.

        Args:
            settings (dict): The settings of the input the sensor is attached to.

        Returns:
            Reading: The values read.

        Raises:
            Exception: If the sensor can't be read.

        """
        sensor_label = settings["label"]

        if self._dummy:
            sensor = self.get_dummy(settings)
        else:
            sensor_type = settings["temp_sensor_type"]
            sensor_class = SENSORS.get(sensor_type)
            if sensor_class is None:
                msg = f"Unsupported sensor type: {sensor_type}"
                raise SensorError(msg)

            try:
                sensor = self._get_sensor(settings, sensor_class)
            except ValueError as error:
                msg = f"Invalid settings: {error}"
                raise SensorError(msg) from error

        reading = sensor.read()
        self._logger.debug("Sensor %s read: %s", sensor_label, reading)
        return reading

    def get_dummy(self, settings: dict) -> DummySensor:
        """Get the dummy sensor of an input.

        Args:
            settings (dict): The settings of the input.

        Returns:
            DummySensor: The dummy sensor of the input.

        """
        return self._get_sensor(settings, DummySensor)

    def _get_sensor(self, settings: dict, sensor_class: type[_SensorT]) -> _SensorT:
        sensor_index = settings["index_id"]
        sensor = self._sensors.get(sensor_index)
        config = sensor_class.parse_config(settings)

        if not isinstance(sensor, sensor_class) or sensor.config != config:
            sensor = sensor_class(self._logger, config)
            self._sensors[sensor_index] = sensor

        return sensor
