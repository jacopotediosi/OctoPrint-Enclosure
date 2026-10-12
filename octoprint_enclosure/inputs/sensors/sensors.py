from __future__ import annotations

from typing import TYPE_CHECKING

from .dummy import DummySensor
from .registry import SENSORS

if TYPE_CHECKING:
    import logging

    from .base import Reading, Sensor


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
        self._sensors: dict[tuple[int, type[Sensor]], Sensor] = {}

    def read(self, config: dict) -> Reading:
        """Read a sensor.

        Args:
            config (dict): The configuration of the sensor.

        Returns:
            Reading: The values read.

        Raises:
            UnsupportedSensorTypeError: If the kind of the sensor is not supported.

        """
        sensor_class = self._get_sensor_class(config)
        if sensor_class is None:
            msg = f"Unsupported sensor type: {config['temp_sensor_type']}"
            raise UnsupportedSensorTypeError(msg)

        key = (config["index_id"], sensor_class)
        if key not in self._sensors:
            self._sensors[key] = sensor_class(self._logger)
        return self._sensors[key].read()

    def _get_sensor_class(self, config: dict) -> type[Sensor] | None:
        return DummySensor if self._dummy else SENSORS.get(config["temp_sensor_type"])
