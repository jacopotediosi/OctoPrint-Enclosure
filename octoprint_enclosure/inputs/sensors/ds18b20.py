from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from typing_extensions import override

from octoprint_enclosure.config import config_field
from octoprint_enclosure.utils import MeasurementType

from .base import PinSensor, PinSensorConfig, Reading, SensorError

DEVICES_DIR = Path("/sys/bus/w1/devices/")


@dataclass(frozen=True)
class Ds18b20Config(PinSensorConfig):
    """The configuration of a DS18B20 sensor."""

    type_help = (
        '<span class="label label-important">Attention</span> This sensor needs 1-Wire enabled: run '
        "<code>sudo raspi-config</code>, enable 1-Wire in the interface options and reboot."
    )

    gpio_pin: int = config_field(
        label="GPIO",
        help_text="GPIO the data line is connected to, usually 4 unless you changed the 1-Wire overlay.",
        min_value=0,
    )
    """The GPIO pin of the data line."""

    ds18b20_serial: str = config_field(
        optional=True,
        label="DS18B20 Serial Number",
        help_text=(
            "Serial number of the sensor, needed when there is more than one. Find it by running "
            "<code>ls /sys/bus/w1/devices</code> on your Raspberry Pi: it looks like <code>28-0123456789ab</code>."
        ),
    )
    """The serial number of the sensor, such as 28-0123456789ab."""


class Ds18b20Sensor(PinSensor[Ds18b20Config]):
    """A DS18B20 temperature sensor, read through the 1-Wire driver of the kernel."""

    config_class = Ds18b20Config
    measurement_types = frozenset({MeasurementType.TEMPERATURE})

    @override
    def read(self) -> Reading:
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
