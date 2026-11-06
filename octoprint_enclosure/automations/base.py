from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.core import REQUIRED, BaseConfig

if TYPE_CHECKING:
    import logging

    from typing_extensions import Self

    from .triggers.base import Trigger


class AutomationError(Exception):
    """Raised when an automation can't be used, with the reason as message."""


@dataclass(frozen=True)
class AutomationConfig(BaseConfig):
    """The configuration shared by all the automations."""

    index_id: int = REQUIRED
    """The id of the automation."""

    automation_type: str = ""
    """The type of the automation."""

    label: str = field(default="", compare=False)
    """The label of the automation."""

    enabled: bool = field(default=True, compare=False)
    """Whether the automation is enabled."""

    show_in_tab: bool = field(default=False, compare=False)
    """Whether the Enclosure tab shows the automation, with a switch to enable or disable it."""


_ConfigT = TypeVar("_ConfigT", bound=AutomationConfig)


class Automation(Generic[_ConfigT]):
    """An automation, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the automation."""

    config: _ConfigT
    """The configuration of the automation."""

    enabled: bool
    """Whether the automation is enabled."""

    _logger: logging.Logger

    def __init__(self, config: _ConfigT, logger: logging.Logger) -> None:
        """Set up the automation.

        Args:
            config (_ConfigT): The configuration of the automation.
            logger (logging.Logger): The logger to write to.

        """
        self.config = config
        self.enabled = config.enabled
        self._logger = logger

    @property
    def trigger(self) -> Trigger | None:
        """What starts the automation, or None if no trigger does."""
        return None

    def has_same_config(self, other: Automation) -> bool:
        """Check whether another automation has the same configuration.

        Args:
            other (Automation): The other automation.

        Returns:
            bool: Whether the other automation is of the same type and has the same configuration.

        """
        return type(other) is type(self) and other.config == self.config

    @classmethod
    def from_settings(cls, settings: dict, logger: logging.Logger) -> Self:
        """Create the automation from its settings.

        Args:
            settings (dict): The settings of the automation.
            logger (logging.Logger): The logger to write to.

        Returns:
            Self: The automation.

        Raises:
            ValueError: If the settings are not valid.

        """
        return cls(cls.config_class.from_settings(settings), logger)
