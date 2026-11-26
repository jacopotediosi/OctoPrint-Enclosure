from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from octoprint_enclosure.config import BaseConfig, config_field
from octoprint_enclosure.outputs import config_with_setpoint_from_settings
from octoprint_enclosure.utils import LabeledEnum, LabeledValue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from typing_extensions import Self


class ReactionType(LabeledEnum):
    """The type of an automation reaction."""

    OUTPUT_CONTROL = LabeledValue(value="output_control", label="Output Control")
    RUN_ACTION = LabeledValue(value="run_action", label="Run Action")


@dataclass(frozen=True)
class ReactionConfig(BaseConfig):
    """The configuration shared by all the automation reactions."""

    type_field_name = "reaction_type"

    reaction_type: ReactionType = config_field(label="Reaction")
    """The type of the reaction."""


_ConfigT = TypeVar("_ConfigT", bound=ReactionConfig)


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
    def from_settings(
        cls,
        settings: dict,
        setpoint_classes: Mapping[int, type[BaseConfig]],
    ) -> Self:
        """Create the reaction from the settings of its automation.

        Args:
            settings (dict): The settings of the automation.
            setpoint_classes (Mapping[int, type[BaseConfig]]): The class of the setpoint of each output, by the id of
                the output.

        Returns:
            Self: The automation reaction.

        Raises:
            ValueError: If the settings are not valid.

        """
        return cls(config_with_setpoint_from_settings(cls.config_class, settings, setpoint_classes))
