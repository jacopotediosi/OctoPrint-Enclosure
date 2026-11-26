from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from octoprint_enclosure.config import BaseConfig, config_field
from octoprint_enclosure.outputs import config_with_setpoint_from_settings
from octoprint_enclosure.utils import N_, LabeledEnum, LabeledValue

from .conditions import CONDITIONS, ConditionConfig, conditions_from_settings

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping, Sequence

    from typing_extensions import Self

    from .conditions import Condition
    from .conditions_state import ConditionsState
    from .triggers.base import Trigger


class AutomationError(Exception):
    """Raised when an automation can't be used, with the reason as message."""


class AutomationType(LabeledEnum):
    """The type of an automation."""

    RULE = LabeledValue(value="rule", label=N_("Rule (Trigger-Reaction)"))
    FILAMENT = LabeledValue(value="filament", label=N_("Filament Sensor"))
    PWM_TEMPERATURE_LINKED = LabeledValue(value="pwm_temperature_linked", label=N_("PWM Linked to Temperature"))
    TOGGLE_TIMER = LabeledValue(value="toggle_timer", label=N_("Toggle Timer"))


@dataclass(frozen=True)
class AutomationConfig(BaseConfig):
    """The configuration shared by all the automations."""

    type_field_name = "automation_type"

    index_id: int = config_field(label=N_("Id"), widget="id")
    """The id of the automation."""

    label: str = config_field(label=N_("Label"), compare=False)
    """The label of the automation."""

    enabled: bool = config_field(
        default=True,
        label=N_("Enabled"),
        compare=False,
    )
    """Whether the automation is enabled."""

    automation_type: AutomationType = config_field(label=N_("Automation Type"))
    """The type of the automation."""

    show_in_tab: bool = config_field(
        default=False,
        label=N_("Show in tab"),
        help_text=N_("Shows the automation in the Enclosure tab, with a switch to enable or disable it."),
        compare=False,
    )
    """Whether the Enclosure tab shows the automation, with a switch to enable or disable it."""


@dataclass(frozen=True)
class NestedItemListDefinition:
    """Describes a list of items nested in the settings of an automation, e.g. its conditions."""

    settings_key: str
    """The key of the settings of the automation that holds the list."""

    item_label: str
    """The name of one item of the list."""

    shared_item_config_class: type[BaseConfig]
    """The dataclass of the configuration shared by all the items."""

    item_type_classes: Mapping[Any, Any]
    """The class implementing each type of item."""


_ConfigT = TypeVar("_ConfigT", bound=AutomationConfig)


class Automation(Generic[_ConfigT]):
    """An automation, generic over the type of its configuration."""

    config_class: type[_ConfigT]
    """The dataclass of the configuration, whose fields are named like the keys of the settings of the automation."""

    config_type_classes: ClassVar[Mapping[Any, Any]] = {}
    """The class implementing each type that the type field of the configuration chooses among, e.g. each trigger.

    Empty if the only type field of the configuration is the type of automation.
    """

    nested_item_lists: ClassVar[Sequence[NestedItemListDefinition]] = (
        NestedItemListDefinition(
            settings_key="conditions",
            item_label=N_("Condition"),
            shared_item_config_class=ConditionConfig,
            item_type_classes=CONDITIONS,
        ),
    )
    """The lists of items nested in the settings of the automation, e.g. its conditions."""

    config: _ConfigT
    """The configuration of the automation."""

    enabled: bool
    """Whether the automation is enabled."""

    conditions: list[Condition]
    """What must be true for the automation to act."""

    _logger: logging.Logger

    def __init__(self, config: _ConfigT, logger: logging.Logger, conditions: Sequence[Condition] = ()) -> None:
        """Set up the automation.

        Args:
            config (_ConfigT): The configuration of the automation.
            logger (logging.Logger): The logger to write to.
            conditions (Sequence[Condition]): What must be true for the automation to act.

        """
        self.config = config
        self.enabled = config.enabled
        self.conditions = list(conditions)
        self._logger = logger

    @property
    def trigger(self) -> Trigger | None:
        """What starts the automation, or None if no trigger does."""
        return None

    @property
    def configs(self) -> list[BaseConfig]:
        """The configurations the automation is made of."""
        return [self.config, *(condition.config for condition in self.conditions)]

    def has_same_config(self, other: Automation) -> bool:
        """Check whether another automation has the same configuration.

        Args:
            other (Automation): The other automation.

        Returns:
            bool: Whether the other automation is of the same type and has the same configuration and conditions.

        """
        return (
            type(other) is type(self)
            and other.config == self.config
            and len(other.conditions) == len(self.conditions)
            and all(
                type(other_condition) is type(condition) and other_condition.config == condition.config
                for condition, other_condition in zip(self.conditions, other.conditions)
            )
        )

    def conditions_satisfied(self, conditions_state: ConditionsState) -> bool:
        """Check whether every condition of the automation is satisfied.

        Args:
            conditions_state (ConditionsState): The current state of the things that the automation conditions check.

        Returns:
            bool: Whether every condition is satisfied.

        """
        return all(condition.is_satisfied(conditions_state) for condition in self.conditions)

    @classmethod
    def from_settings(
        cls,
        settings: dict,
        logger: logging.Logger,
        setpoint_classes: Mapping[int, type[BaseConfig]],
    ) -> Self:
        """Create the automation from its settings.

        Args:
            settings (dict): The settings of the automation.
            logger (logging.Logger): The logger to write to.
            setpoint_classes (Mapping[int, type[BaseConfig]]): The class of the setpoint of each output, by the id of
                the output.

        Returns:
            Self: The automation.

        Raises:
            ValueError: If the settings are not valid.

        """
        config = config_with_setpoint_from_settings(cls.config_class, settings, setpoint_classes)
        return cls(config, logger, conditions_from_settings(settings))
