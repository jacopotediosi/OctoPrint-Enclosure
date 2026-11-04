from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.core import BaseConfig

if TYPE_CHECKING:
    from typing_extensions import Self

    from octoprint_enclosure.automations.events import AutomationEvent

_ConfigT = TypeVar("_ConfigT", bound=BaseConfig)


class Trigger(ABC, Generic[_ConfigT]):
    """What starts an automation, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the automation."""

    config: _ConfigT
    """The configuration of the automation trigger."""

    def __init__(self, config: _ConfigT) -> None:
        """Set up the trigger.

        Args:
            config (_ConfigT): The configuration of the automation trigger.

        """
        self.config = config

    @classmethod
    def from_settings(cls, settings: dict) -> Self:
        """Create the trigger from the settings of its automation.

        Args:
            settings (dict): The settings of the automation.

        Returns:
            Self: The automation trigger.

        Raises:
            ValueError: If the settings are not valid.

        """
        return cls(cls.config_class.from_settings(settings))

    @abstractmethod
    def matches(self, event: AutomationEvent) -> bool:
        """Check whether an event starts the automation.

        Args:
            event (AutomationEvent): What happened.

        Returns:
            bool: Whether the event starts the automation.

        """
