from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from pathlib import Path
from subprocess import run

from typing_extensions import override

from .base import Reading, Sensor

DEVICES_DIR = Path("/sys/bus/w1/devices/")


@dataclass(frozen=True)
class Ds18b20Config:
    """The configuration of a DS18B20 sensor."""

    ds18b20_serial: str
    """The serial number of the sensor, such as 28-0123456789ab."""


class Ds18b20Sensor(Sensor[Ds18b20Config]):
    """A DS18B20 temperature sensor, read through the 1-Wire driver of the kernel."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> Ds18b20Config:
        return Ds18b20Config(ds18b20_serial=str(settings["ds18b20_serial"]))

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
        if equals_pos != -1:
            temp_string = lines[1][equals_pos + 2 :]
            temp_c = float(temp_string) / 1000.0
            return Reading(temperature=round(temp_c, 1))
        return Reading(temperature=-1)

    def _read_lines(self) -> list[str]:
        device_folder = next(DEVICES_DIR.glob(self.config.ds18b20_serial + "*"))
        device_file = device_folder / "w1_slave"
        with device_file.open() as device_file_result:
            return device_file_result.readlines()
