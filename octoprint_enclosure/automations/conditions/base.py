from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.settings import BaseConfig

if TYPE_CHECKING:
    from typing_extensions import Self

_ConfigT = TypeVar("_ConfigT", bound=BaseConfig)


class Condition(ABC, Generic[_ConfigT]):
    """What must be true for an automation to act, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the condition."""

    config: _ConfigT
    """The configuration of the automation condition."""

    def __init__(self, config: _ConfigT) -> None:
        """Set up the automation condition.

        Args:
            config (_ConfigT): The configuration of the automation condition.

        """
        self.config = config

    @classmethod
    def from_settings(cls, settings: dict) -> Self:
        """Create the automation condition from its settings.

        Args:
            settings (dict): The settings of the automation condition.

        Returns:
            Self: The automation condition.

        Raises:
            ValueError: If the settings are not valid.

        """
        return cls(cls.config_class.from_settings(settings))

    @abstractmethod
    def is_satisfied(self, *, printing: bool) -> bool:
        """Check whether the automation condition is satisfied.

        Args:
            printing (bool): Whether a print job is running.

        Returns:
            bool: Whether the automation condition is satisfied.

        """
