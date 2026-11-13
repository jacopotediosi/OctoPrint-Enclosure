from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.settings import REQUIRED, ActionId

from .base import Automation, AutomationConfig
from .events import GpioEdgeEvent
from .triggers import GpioInputTrigger

if TYPE_CHECKING:
    import logging

    from typing_extensions import Self

    from octoprint_enclosure.settings import BaseConfig

MIN_PRESENCE_SECONDS = 90
"""The seconds the filament has to be present before its end counts."""


@dataclass(frozen=True)
class FilamentConfig(AutomationConfig):
    """The configuration of an automation that runs an action when a sensor detects the end of the filament."""

    action: ActionId = REQUIRED
    """The id of the action run when the filament ends."""


class FilamentAutomation(Automation[FilamentConfig]):
    """An automation that runs an action when a sensor detects the end of the filament."""

    config_class = FilamentConfig

    _trigger: GpioInputTrigger
    """The GPIO input of the sensor, with the edge that means that the filament is missing."""

    _present_since: float | None
    """When the filament was last found present, as a time.monotonic() timestamp, or None while it is missing."""

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
        self._present_since = None

    @property
    @override
    def trigger(self) -> GpioInputTrigger:
        """The GPIO input of the filament sensor, with the edge that means that the filament is missing."""
        return self._trigger

    @property
    @override
    def configs(self) -> list[BaseConfig]:
        """The configurations the automation is made of."""
        return [*super().configs, self.trigger.config]

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
        return self.trigger.matches(GpioEdgeEvent(self.trigger.config.input, level))

    def update_filament_presence(self, level: int) -> None:
        """Update since when the filament is present from a level of the input of the sensor.

        Args:
            level (int): The level of the input, 1 if high or 0 if low.

        """
        if self.is_filament_missing(level):
            self._present_since = None
        elif self._present_since is None:
            self._present_since = time.monotonic()

    def detect_filament_end(self, *, printing: bool) -> bool:
        """Check whether the filament ended, when the input of the sensor has the edge that means that it is missing.

        Args:
            printing (bool): Whether OctoPrint is printing, and not paused.

        Returns:
            bool: Whether the filament ended: only while printing, and only if the filament was present for
                MIN_PRESENCE_SECONDS, otherwise a change of the filament is still going on.

        """
        present_since = self._present_since
        self._present_since = None
        if not self.enabled or not printing or present_since is None:
            return False

        if time.monotonic() - present_since < MIN_PRESENCE_SECONDS:
            self._logger.info(
                "Ignored the end of the filament: it was present for less than %s seconds.",
                MIN_PRESENCE_SECONDS,
            )
            return False

        self._logger.info("Detected end of filament.")
        return True
