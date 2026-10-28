from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Reading, Sensor, SensorError

WORKER_PATH = Path(__file__).with_name("dht_worker.py")
WORKER_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class DhtConfig(BaseConfig):
    """The configuration of a DHT sensor."""

    gpio_pin: int
    """The GPIO pin the sensor is connected to."""


class _DhtSensor(Sensor[DhtConfig]):
    """A DHT temperature and humidity sensor."""

    config_class = DhtConfig

    _model: ClassVar[str]
    """The model of the sensor."""

    @override
    def read(self) -> Reading:
        command = [sys.executable, str(WORKER_PATH), self._model, str(self.config.gpio_pin)]

        # Read the sensor
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=WORKER_TIMEOUT_SECONDS,
            check=False,
        )

        # Check for errors
        if result.returncode != 0:
            raise SensorError(result.stderr.strip())

        # The worker prints the temperature and the humidity, separated by a space
        temperature, humidity = (float(value) for value in result.stdout.split())

        return Reading(temperature=round(temperature, 1), humidity=round(humidity, 1))


class Dht11Sensor(_DhtSensor):
    """A DHT11 temperature and humidity sensor."""

    _model = "DHT11"


class Dht22Sensor(_DhtSensor):
    """A DHT22 (or AM2302) temperature and humidity sensor."""

    _model = "DHT22"
