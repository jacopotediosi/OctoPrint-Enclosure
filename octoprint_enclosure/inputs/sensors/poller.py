from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import Reading

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterable

    from .base import Sensor
    from .sensors import Sensors

READ_INTERVAL_SECONDS = 10
READING_MAX_AGE_SECONDS = 30


@dataclass(frozen=True)
class ReadingOutcome:
    """The outcome of reading a sensor."""

    reading: Reading | None
    """The values read, or None if the sensor couldn't be read."""

    error: Exception | None
    """Why the sensor couldn't be read, or None."""

    time: float
    """When the sensor was read, as a monotonic time."""


class SensorPoller:
    """Reads the sensors, each on a thread of its own, and keeps the last reading of each."""

    _sensors: Sensors
    """The sensors class."""

    _on_reading: Callable[[int, ReadingOutcome], object]
    """The function called after each reading, with the id of the input and the outcome of the reading."""

    _logger: logging.Logger

    _started: bool
    """Whether the sensor poller has been started."""

    _outcomes: dict[int, ReadingOutcome]
    """The outcome of the last reading of each sensor, by the id of its input."""

    _polled: dict[int, Sensor]
    """The sensor to read for each input, by the id of the input."""

    _stale: set[int]
    """The ids of the inputs whose sensor stopped answering."""

    _lock: threading.Lock
    """Held by every access to the sensors and the readings."""

    def __init__(
        self,
        sensors: Sensors,
        on_reading: Callable[[int, ReadingOutcome], object],
        logger: logging.Logger,
    ) -> None:
        """Set up the poller, with no sensor until some settings are loaded.

        Args:
            sensors (Sensors): The sensors.
            on_reading (Callable[[int, ReadingOutcome], object]): The function called after each reading, on the
                thread that read the sensor, with the id of the input and the outcome of the reading.
            logger (logging.Logger): The logger to write to.

        """
        self._sensors = sensors
        self._on_reading = on_reading
        self._logger = logger.getChild("SensorPoller")

        self._started = False
        self._outcomes = {}
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
                self._outcomes.pop(index_id, None)
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

    def get_reading(self, index_id: int) -> Reading:
        """Get the last reading of an input.

        Args:
            index_id (int): The id of the input.

        Returns:
            Reading: The reading, with all its values None if the last reading of the sensor failed, is too old or is
                still to come.

        Raises:
            LookupError: If the input has no sensor.

        """
        with self._lock:
            if index_id not in self._polled:
                msg = f"Input {index_id} has no sensor"
                raise LookupError(msg)
            return self._get_reading(index_id, time.monotonic())

    def get_readings(self) -> dict[int, Reading]:
        """Get the last reading of each input with a sensor.

        Returns:
            dict[int, Reading]: The reading of each input, by its id, with all its values None if the last reading of
                the sensor failed, is too old or is still to come.

        """
        with self._lock:
            now = time.monotonic()
            return {index_id: self._get_reading(index_id, now) for index_id in self._polled}

    def _get_reading(self, index_id: int, now: float) -> Reading:
        outcome = self._outcomes.get(index_id)

        if outcome is None or outcome.reading is None:
            return Reading()

        if now - outcome.time > READING_MAX_AGE_SECONDS:
            if index_id not in self._stale:
                # Reading is stale for the first time
                self._stale.add(index_id)
                self._logger.warning(
                    "The sensor of input %s stopped answering: its last reading is %.0f s old",
                    index_id,
                    now - outcome.time,
                )
            return Reading()

        return outcome.reading

    def _start_reading(self, index_id: int, sensor: Sensor) -> None:
        polled_position = list(self._polled).index(index_id)
        shift_seconds = polled_position * READ_INTERVAL_SECONDS / len(self._polled)

        thread = threading.Thread(
            target=self._poll,
            args=(index_id, sensor, shift_seconds),
            name=f"EnclosureSensor{index_id}",
        )
        thread.daemon = True
        thread.start()

    def _poll(self, index_id: int, sensor: Sensor, shift_seconds: float) -> None:
        read_interval_seconds = READ_INTERVAL_SECONDS + shift_seconds

        while True:
            # End the thread if its sensor is gone or replaced
            with self._lock:
                if self._polled.get(index_id) is not sensor:
                    return

            # Read the sensor
            started = time.monotonic()
            self._read(index_id, sensor)

            # Sleep until the next reading
            time.sleep(max(0, read_interval_seconds - (time.monotonic() - started)))
            read_interval_seconds = READ_INTERVAL_SECONDS

    def _read(self, index_id: int, sensor: Sensor) -> None:
        # Get the reading
        try:
            reading = sensor.read()
        except Exception as error:  # noqa: BLE001 - the error is kept in the outcome of the reading
            self._logger.debug("Couldn't read the sensor of input %s: %s", index_id, error)
            outcome = ReadingOutcome(None, error, time.monotonic())
        else:
            self._logger.debug("Read the sensor of input %s: %s", index_id, reading)
            outcome = ReadingOutcome(reading, None, time.monotonic())

        # Save the outcome
        with self._lock:
            # A sensor gone or replaced meanwhile leaves no reading behind
            if self._polled.get(index_id) is not sensor:
                return

            self._outcomes[index_id] = outcome

            answers_again = index_id in self._stale and outcome.error is None
            self._stale.discard(index_id)

        # Notify if a stale reading answers again
        if answers_again:
            self._logger.info("The sensor of input %s answers again", index_id)

        # Call the reading callback
        try:
            self._on_reading(index_id, outcome)
        except Exception:
            self._logger.exception("Error handling a reading of the sensor of input %s", index_id)
