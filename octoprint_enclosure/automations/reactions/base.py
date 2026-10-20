from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.core import BaseConfig

if TYPE_CHECKING:
    from typing_extensions import Self

_ConfigT = TypeVar("_ConfigT", bound=BaseConfig)


class Reaction(Generic[_ConfigT]):
    """What an automation does, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the automation."""

    config: _ConfigT
    """The configuration of the reaction."""

    def __init__(self, config: _ConfigT) -> None:
        """Set up the reaction.

        Args:
            config (_ConfigT): The configuration of the automation reaction.

        """
        self.config = config

    @classmethod
    def from_settings(cls, settings: dict) -> Self:
        """Create the reaction from the settings of its automation.

        Args:
            settings (dict): The settings of the automation.

        Returns:
            Self: The automation reaction.

        Raises:
            ValueError: If the settings are not valid.

        """
        return cls(cls.config_class.from_settings(settings))
