from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.settings import BaseConfig, setting

if TYPE_CHECKING:
    from typing_extensions import Self

    from octoprint_enclosure.automations.conditions_state import ConditionsState


@dataclass(frozen=True)
class ConditionConfig(BaseConfig):
    """The configuration shared by all the automation conditions."""

    condition_type: str = setting(default="print_job", label="Condition")
    """The type of the condition."""


_ConfigT = TypeVar("_ConfigT", bound=ConditionConfig)


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
    def is_satisfied(self, conditions_state: ConditionsState) -> bool:
        """Check whether the automation condition is satisfied.

        Args:
            conditions_state (ConditionsState): The current state of the things that the automation conditions check.

        Returns:
            bool: Whether the automation condition is satisfied.

        """
