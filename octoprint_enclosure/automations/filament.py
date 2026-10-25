from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Automation
from .triggers import GpioInputTrigger

if TYPE_CHECKING:
    import logging

    from typing_extensions import Self


@dataclass(frozen=True)
class FilamentConfig(BaseConfig):
    """The configuration of an automation that changes the filament when a sensor detects its end."""

    filament_sensor_enabled: bool
    """Whether the end of the filament is detected."""

    filament_sensor_timeout: int
    """The seconds after an end of the filament during which another end is ignored."""


class FilamentAutomation(Automation[FilamentConfig]):
    """An automation that changes the filament when a sensor detects its end."""

    config_class = FilamentConfig

    _trigger: GpioInputTrigger
    """The GPIO input of the sensor, with the edge that means that the filament is missing."""

    enabled: bool
    """Whether the filament detection is enabled."""

    _armed: bool
    """Whether the automation is actually watching for the end of the filament."""

    _last_detection_time: float
    """When the end of the filament was last detected, as a timestamp, or 0 if not since the detection was armed."""

    def __init__(self, config: FilamentConfig, trigger: GpioInputTrigger, logger: logging.Logger) -> None:
        """Set up the filament detection automation.

        Args:
            config (FilamentConfig): The configuration of the automation.
            trigger (GpioInputTrigger): The GPIO input of the sensor, with the edge that means that the filament is
                missing.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, logger)
        self._trigger = trigger
        self.enabled = config.filament_sensor_enabled
        self._armed = False
        self._last_detection_time = 0

    @property
    @override
    def trigger(self) -> GpioInputTrigger:
        """The GPIO input of the filament sensor, with the edge that means that the filament is missing."""
        return self._trigger

    @override
    def has_same_config(self, other: Automation) -> bool:
        return (
            isinstance(other, FilamentAutomation)
            and super().has_same_config(other)
            and other.trigger.config == self.trigger.config
        )

    @classmethod
    @override
    def from_settings(cls, settings: dict, logger: logging.Logger) -> Self:
        return cls(FilamentConfig.from_settings(settings), GpioInputTrigger.from_settings(settings), logger)

    def is_filament_missing(self, level: int) -> bool:
        """Check whether a level of the input of the sensor means that the filament is missing.

        Args:
            level (int): The level of the input, 1 if high or 0 if low.

        Returns:
            bool: Whether the filament is missing.

        """
        return self.trigger.matches_level(level)

    @property
    def is_armed(self) -> bool:
        """Whether the automation is actually watching for the end of the filament."""
        return self._armed

    def arm(self) -> None:
        """Start detecting the end of the filament."""
        self._armed = True
        self._last_detection_time = 0

    def disarm(self) -> None:
        """Stop detecting the end of the filament."""
        self._armed = False

    def detect_end(self) -> bool:
        """Check whether the filament ended.

        Returns:
            bool: Whether the filament ended.

        """
        if not self._armed or not self.enabled:
            return False

        now = time.time()
        if int(now - self._last_detection_time) <= self.config.filament_sensor_timeout:
            self._logger.info("Prevented end of filament detection, filament sensor timeout not elapsed.")
            return False

        self._logger.info("Detected end of filament.")
        self._last_detection_time = now
        return True
