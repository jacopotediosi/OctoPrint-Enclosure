from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from subprocess import run

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Reading, Sensor, SensorError

DEVICES_DIR = Path("/sys/bus/w1/devices/")


@dataclass(frozen=True)
class Ds18b20Config(BaseConfig):
    """The configuration of a DS18B20 sensor."""

    ds18b20_serial: str = ""
    """The serial number of the sensor, such as 28-0123456789ab."""


class Ds18b20Sensor(Sensor[Ds18b20Config]):
    """A DS18B20 temperature sensor, read through the 1-Wire driver of the kernel."""

    config_class = Ds18b20Config

    @override
    def read(self) -> Reading:
        with contextlib.suppress(OSError):
            run(["modprobe", "w1-gpio"], check=False)
            run(["modprobe", "w1-therm"], check=False)

        lines = self._read_lines()
        while lines[0].strip()[-3:] != "YES":
            time.sleep(0.2)
            lines = self._read_lines()
        equals_pos = lines[1].find("t=")
        if equals_pos == -1:
            msg = f"No temperature in the sensor output: {lines[1].strip()}"
            raise SensorError(msg)

        temp_string = lines[1][equals_pos + 2 :]
        temp_c = float(temp_string) / 1000.0
        return Reading(temperature=round(temp_c, 1))

    def _read_lines(self) -> list[str]:
        device_folder = next(DEVICES_DIR.glob(self.config.ds18b20_serial + "*"), None)
        if device_folder is None:
            msg = f"No 1-Wire device with serial {self.config.ds18b20_serial}"
            raise SensorError(msg)

        device_file = device_folder / "w1_slave"
        with device_file.open() as device_file_result:
            return device_file_result.readlines()
