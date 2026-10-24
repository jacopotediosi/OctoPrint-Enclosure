from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterable

    from .base import Reading, Sensor
    from .sensors import Sensors

READ_INTERVAL_SECONDS = 10
READING_MAX_AGE_SECONDS = 30


class StaleReadingError(Exception):
    """The error of a sensor that stopped answering."""


@dataclass(frozen=True)
class SensorReading:
    """The outcome of reading a sensor."""

    reading: Reading | None
    """The values read, or None if there is no current value."""

    error: Exception | None
    """Why there is no current value, because the sensor couldn't be read or its last reading is too old, or None."""

    time: float
    """When the sensor was read, as a monotonic time."""


class SensorPoller:
    """Reads the sensors, each on a thread of its own, and keeps the last reading of each."""

    _sensors: Sensors
    """The sensors class."""

    _on_reading: Callable[[int, SensorReading], object]
    """The function called after each reading, with the id of the input and the reading outcome."""

    _logger: logging.Logger

    _started: bool
    """Whether the sensor poller has been started."""

    _readings: dict[int, SensorReading]
    """The last reading of each sensor, by the id of its input."""

    _polled: dict[int, Sensor]
    """The sensor to read for each input, by the id of the input."""

    _stale: set[int]
    """The ids of the inputs whose sensor stopped answering."""

    _lock: threading.Lock
    """Held by every access to the sensors and the readings."""

    def __init__(
        self,
        sensors: Sensors,
        on_reading: Callable[[int, SensorReading], object],
        logger: logging.Logger,
    ) -> None:
        """Set up the poller, with no sensor until some settings are loaded.

        Args:
            sensors (Sensors): The sensors.
            on_reading (Callable[[int, SensorReading], object]): The function called after each reading, on the
                thread that read the sensor, with the id of the input and the outcome.
            logger (logging.Logger): The logger to write to.

        """
        self._sensors = sensors
        self._on_reading = on_reading
        self._logger = logger.getChild("SensorPoller")

        self._started = False
        self._readings = {}
        self._polled = {}
        self._stale = set()
        self._lock = threading.Lock()

    def load(self, sensor_inputs_settings: Iterable[dict]) -> None:
        """Load the sensors of some inputs from their settings.

        Args:
            sensor_inputs_settings (Iterable[dict]): The settings of the inputs with a temperature sensor.

        """
        self._sensors.load(sensor_inputs_settings)
        sensors = self._sensors.get_all()

        with self._lock:
            # Handle sensors gone or replaced
            for index_id, sensor in list(self._polled.items()):
                if sensors.get(index_id) is sensor:
                    continue
                del self._polled[index_id]
                self._readings.pop(index_id, None)
                self._stale.discard(index_id)

            # Handle new sensors
            for index_id, sensor in sensors.items():
                if index_id in self._polled:
                    continue
                self._polled[index_id] = sensor
                if self._started:
                    self._start_reading(index_id, sensor)

    def start(self) -> None:
        """Start reading the sensors."""
        with self._lock:
            self._started = True
            for index_id, sensor in self._polled.items():
                self._start_reading(index_id, sensor)

    def read_all(self) -> None:
        """Read every sensor now, on the calling thread."""
        with self._lock:
            polled = dict(self._polled)
        for index_id, sensor in polled.items():
            self._read(index_id, sensor)

    def get_readings(self) -> dict[int, SensorReading]:
        """Get the last reading of each sensor.

        Returns:
            dict[int, SensorReading]: The last reading of each sensor read at least once, by the id of its input.

        """
        with self._lock:
            now = time.monotonic()
            readings: dict[int, SensorReading] = {}

            for index_id, last_reading in self._readings.items():
                age = now - last_reading.time

                if age <= READING_MAX_AGE_SECONDS:
                    # Reading is not stale
                    readings[index_id] = last_reading
                    continue

                if index_id not in self._stale:
                    # Reading is stale for the first time
                    self._stale.add(index_id)
                    self._logger.warning(
                        "The sensor of input %s stopped answering: its last reading is %.0f s old",
                        index_id,
                        age,
                    )

                error = StaleReadingError(f"The last reading is {age:.0f} s old")
                readings[index_id] = SensorReading(None, error, last_reading.time)

            return readings

    def _start_reading(self, index_id: int, sensor: Sensor) -> None:
        thread = threading.Thread(target=self._poll, args=(index_id, sensor), name=f"EnclosureSensor{index_id}")
        thread.daemon = True
        thread.start()

    def _poll(self, index_id: int, sensor: Sensor) -> None:
        while True:
            # End the thread if its sensor is gone or replaced
            with self._lock:
                if self._polled.get(index_id) is not sensor:
                    return

            # Read the sensor
            started = time.monotonic()
            self._read(index_id, sensor)

            # Sleep until the next reading
            time.sleep(max(0, READ_INTERVAL_SECONDS - (time.monotonic() - started)))

    def _read(self, index_id: int, sensor: Sensor) -> None:
        # Get the reading
        now = time.monotonic()
        try:
            reading = sensor.read()
        except Exception as error:
            self._logger.debug("Couldn't read the sensor of input %s: %s", index_id, error)
            sensor_reading = SensorReading(None, error, now)
        else:
            self._logger.debug("Read the sensor of input %s: %s", index_id, reading)
            sensor_reading = SensorReading(reading, None, now)

        # Save the reading
        with self._lock:
            # A sensor gone or replaced meanwhile leaves no reading behind
            if self._polled.get(index_id) is not sensor:
                return

            self._readings[index_id] = sensor_reading

            answers_again = index_id in self._stale
            self._stale.discard(index_id)

        # Notify if a stale reading answers again
        if answers_again:
            self._logger.info("The sensor of input %s answers again", index_id)

        # Call the reading callback
        try:
            self._on_reading(index_id, sensor_reading)
        except Exception:
            self._logger.exception("Error handling a reading of the sensor of input %s", index_id)
