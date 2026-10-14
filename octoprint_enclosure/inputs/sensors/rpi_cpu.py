from __future__ import annotations

from dataclasses import dataclass

from gpiozero import CPUTemperature
from typing_extensions import override

from .base import Reading, Sensor


@dataclass(frozen=True)
class RpiCpuConfig:
    """The configuration of a Raspberry Pi CPU temperature sensor."""


class RpiCpuSensor(Sensor[RpiCpuConfig]):
    """A Raspberry Pi CPU temperature sensor."""

    @classmethod
    @override
    def parse_config(cls, settings: dict) -> RpiCpuConfig:
        return RpiCpuConfig()

    @override
    def read(self) -> Reading:
        return Reading(temperature=round(CPUTemperature().temperature, 1))
