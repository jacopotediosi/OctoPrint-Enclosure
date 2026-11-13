from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .base import Reading, SensorError

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterable

    from .base import Sensor
    from .sensors import Sensors

READ_INTERVAL_SECONDS = 10
READING_MAX_AGE_SECONDS = 30


@dataclass(frozen=True)
class _ReadingOutcome:
    """The outcome of reading a sensor."""

    reading: Reading | None
    """The values read, or None if the sensor couldn't be read."""

    error: Exception | None
    """Why the sensor couldn't be read, or None."""

    time: float
    """When the sensor was read, as a monotonic time."""


class _SensorState(Enum):
    """Whether a sensor can be read."""

    WORKING = "working"
    """The last reading gave its values."""

    FAILING = "failing"
    """The last reading gave an error."""

    STUCK = "stuck"
    """The sensor doesn't answer: its last good reading is too old, or its first reading never ended."""


class SensorPoller:
    """Reads the sensors, each on a thread of its own, and keeps the last reading and the state of each."""

    _sensors: Sensors
    """The sensors class."""

    _logger: logging.Logger

    _on_reading: Callable[[int], object] | None
    """The function called after each reading, with the id of the input, or None until the poller is started."""

    _on_failure: Callable[[int], object] | None
    """The function called when a sensor stops working, with the id of its input, or None until the poller is
    started."""

    _started: bool
    """Whether the sensor poller has been started."""

    _outcomes: dict[int, _ReadingOutcome]
    """The outcome of the last reading of each sensor, by the id of its input."""

    _states: dict[int, _SensorState]
    """The state of each sensor, by the id of its input."""

    _started_at: dict[int, float]
    """When each sensor started being read, as a monotonic time, by the id of its input."""

    _polled: dict[int, Sensor]
    """The sensor to read for each input, by the id of the input."""

    _lock: threading.Lock
    """Held by every access to the sensors, the readings and the states."""

    def __init__(self, sensors: Sensors, logger: logging.Logger) -> None:
        """Set up the poller, with no sensor until some settings are loaded.

        Args:
            sensors (Sensors): The sensors.
            logger (logging.Logger): The logger to write to.

        """
        self._sensors = sensors
        self._logger = logger.getChild("SensorPoller")

        self._on_reading = None
        self._on_failure = None
        self._started = False
        self._outcomes = {}
        self._states = {}
        self._started_at = {}
        self._polled = {}
        self._lock = threading.Lock()

    def load(self, inputs_settings: Iterable[dict]) -> None:
        """Load the sensors of some inputs from their settings.

        Args:
            inputs_settings (Iterable[dict]): The settings of the inputs.

        """
        self._sensors.load(inputs_settings)
        sensors = self._sensors.get_all()

        with self._lock:
            # Handle sensors gone or replaced
            for index_id, sensor in list(self._polled.items()):
                if sensors.get(index_id) is sensor:
                    continue
                del self._polled[index_id]
                self._outcomes.pop(index_id, None)
                self._states.pop(index_id, None)
                self._started_at.pop(index_id, None)

            # Handle new sensors
            for index_id, sensor in sensors.items():
                if index_id in self._polled:
                    continue
                self._polled[index_id] = sensor
                if self._started:
                    self._start_reading(index_id, sensor)

    def start(self, on_reading: Callable[[int], object], on_failure: Callable[[int], object]) -> None:
        """Start reading the sensors.

        Args:
            on_reading (Callable[[int], object]): The function called after each reading, good or failed, on the
                thread that read the sensor, with the id of the input.
            on_failure (Callable[[int], object]): The function called when a sensor stops working, with the id of its
                input: its reading failed, or it doesn't answer.

        """
        with self._lock:
            self._on_reading = on_reading
            self._on_failure = on_failure
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
        self._detect_stuck_sensors()

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
        self._detect_stuck_sensors()

        with self._lock:
            now = time.monotonic()
            return {index_id: self._get_reading(index_id, now) for index_id in self._polled}

    def _get_reading(self, index_id: int, now: float) -> Reading:
        outcome = self._outcomes.get(index_id)

        if outcome is None or outcome.reading is None or now - outcome.time > READING_MAX_AGE_SECONDS:
            return Reading()

        return outcome.reading

    def _detect_stuck_sensors(self) -> None:
        stopped_working = []

        # Find the sensors whose last good reading became too old, or whose first reading never ended
        with self._lock:
            now = time.monotonic()
            for index_id in self._polled:
                if self._states.get(index_id) in (_SensorState.FAILING, _SensorState.STUCK):
                    continue

                outcome = self._outcomes.get(index_id)
                last_answer = self._started_at.get(index_id) if outcome is None else outcome.time
                if last_answer is None or now - last_answer <= READING_MAX_AGE_SECONDS:
                    continue

                self._states[index_id] = _SensorState.STUCK
                self._logger.error("The sensor of input %s hasn't answered for %.0f s", index_id, now - last_answer)
                stopped_working.append(index_id)

        # Call the failure callback
        for index_id in stopped_working:
            try:
                if self._on_failure is not None:
                    self._on_failure(index_id)
            except Exception:
                self._logger.exception("Error handling the failure of the sensor of input %s", index_id)

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
        self._started_at[index_id] = time.monotonic()

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
            outcome = _ReadingOutcome(None, error, time.monotonic())
        else:
            self._logger.debug("Read the sensor of input %s: %s", index_id, reading)
            outcome = _ReadingOutcome(reading, None, time.monotonic())

        # Save the outcome and the state of the sensor
        with self._lock:
            # A sensor gone or replaced meanwhile leaves no reading behind
            if self._polled.get(index_id) is not sensor:
                return

            self._outcomes[index_id] = outcome

            previous_state = self._states.get(index_id)
            state = _SensorState.WORKING if outcome.error is None else _SensorState.FAILING
            self._states[index_id] = state

        # Log the sensor that stops working or works again
        if state is _SensorState.FAILING and previous_state is not _SensorState.FAILING:
            self._logger.error(
                "The sensor of input %s can't be read: %s",
                index_id,
                outcome.error,
                exc_info=None if isinstance(outcome.error, SensorError) else outcome.error,
            )
        elif state is _SensorState.WORKING and previous_state in (_SensorState.FAILING, _SensorState.STUCK):
            self._logger.warning("The sensor of input %s works again", index_id)

        # Call the reading callback
        try:
            if self._on_reading is not None:
                self._on_reading(index_id)
        except Exception:
            self._logger.exception("Error handling a reading of the sensor of input %s", index_id)

        # Call the failure callback
        if state is _SensorState.FAILING and previous_state in (None, _SensorState.WORKING):
            try:
                if self._on_failure is not None:
                    self._on_failure(index_id)
            except Exception:
                self._logger.exception("Error handling the failure of the sensor of input %s", index_id)
