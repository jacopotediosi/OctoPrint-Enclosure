from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.settings import setting
from octoprint_enclosure.utils import LabeledEnum, LabeledValue, parse_hhmm, seconds_until_next

from .base import Automation, AutomationConfig, NestedItemListDefinition
from .conditions import conditions_from_settings
from .reactions import REACTIONS, OutputControlReaction, OutputSetState, ReactionConfig
from .triggers import TRIGGERS, TriggerType

if TYPE_CHECKING:
    import logging

    from typing_extensions import Self

    from octoprint_enclosure.outputs import OutputSetpointConfig
    from octoprint_enclosure.settings import BaseConfig, OutputId

    from .conditions import Condition
    from .reactions.base import Reaction
    from .triggers.base import Trigger


class RuleTiming(LabeledEnum):
    """When a rule runs its reactions, once its trigger fires."""

    NOW = LabeledValue(value="now", label="Right away")
    DELAY = LabeledValue(value="delay", label="After a delay")
    AT = LabeledValue(value="at", label="At a time of day")


@dataclass(frozen=True)
class RuleConfig(AutomationConfig):
    """The configuration of an automation rule."""

    type_help = (
        '<span class="label label-info">Info:</span> Does something when its trigger happens, for example controls an '
        "output when a button connected to a GPIO input is pressed, or when the temperature goes above a threshold."
    )

    type_field_name = "trigger_type"

    trigger_type: TriggerType = setting(label="Trigger")
    """The type of the trigger of the rule."""

    timing: RuleTiming = setting(
        default=RuleTiming.NOW,
        label="Run",
        help_text="When to run the reactions, once the trigger fires.",
    )
    """When to run the reactions, once the trigger fires."""

    delay: float = setting(
        default=0,
        label="Delay",
        help_text="Seconds to wait after the trigger before running the reactions.",
        unit="s",
        min_value=0,
        visible_if={"timing": ["delay"]},
    )
    """The seconds to wait after the trigger before running the reactions, for a rule that runs after a delay."""

    at: str = setting(
        optional=True,
        label="At",
        help_text="Time of day, as <code>HH:MM</code>: the reactions run the next time it comes after the trigger.",
        visible_if={"timing": ["at"]},
    )
    """The time of day, as HH:MM, at which to run the reactions, for a rule that runs at a time of day."""

    def __post_init__(self) -> None:
        """Check the rule config correctness.

        Raises:
            ValueError: If the rule runs at a time of day that is not HH:MM.

        """
        if self.timing is RuleTiming.AT and parse_hhmm(self.at) is None:
            msg = "at must be a time of day as HH:MM"
            raise ValueError(msg)

    def delay_seconds(self) -> float:
        """Get how long to wait before running the reactions, from now.

        Returns:
            float: The seconds to wait before running the reactions.

        """
        time_of_day = parse_hhmm(self.at) if self.timing is RuleTiming.AT else None
        if time_of_day is not None:
            return seconds_until_next(time_of_day)
        return self.delay if self.timing is RuleTiming.DELAY else 0


class RuleAutomation(Automation[RuleConfig]):
    """An automation that reacts to a trigger, with one or more reactions, when its conditions are satisfied."""

    config_class = RuleConfig

    config_type_classes = TRIGGERS

    nested_item_lists = (
        *Automation.nested_item_lists,
        NestedItemListDefinition(
            settings_key="reactions",
            item_label="Reaction",
            shared_item_config_class=ReactionConfig,
            item_type_classes=REACTIONS,
        ),
    )

    _trigger: Trigger
    """What starts the rule."""

    reactions: list[Reaction]
    """What the rule does, in order."""

    def __init__(
        self,
        config: RuleConfig,
        trigger: Trigger,
        conditions: list[Condition],
        reactions: list[Reaction],
        logger: logging.Logger,
    ) -> None:
        """Set up the automation rule.

        Args:
            config (RuleConfig): The configuration of the automation rule.
            trigger (Trigger): What starts the automation rule.
            conditions (list[Condition]): What must be true when the reactions run.
            reactions (list[Reaction]): What the automation rule does, in order.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, logger, conditions)
        self._trigger = trigger
        self.reactions = reactions

    @property
    @override
    def trigger(self) -> Trigger:
        """What starts the rule."""
        return self._trigger

    @property
    @override
    def configs(self) -> list[BaseConfig]:
        """The configurations the rule is made of."""
        return [*super().configs, self.trigger.config, *(reaction.config for reaction in self.reactions)]

    @override
    def get_output_setpoints(self) -> list[tuple[OutputId, OutputSetpointConfig]]:
        return [
            (reaction.config.controlled_io, reaction.config)
            for reaction in self.reactions
            if isinstance(reaction, OutputControlReaction)
            and reaction.config.controlled_io_set_state is not OutputSetState.OFF
        ]

    @override
    def has_same_config(self, other: Automation) -> bool:
        return (
            isinstance(other, RuleAutomation)
            and super().has_same_config(other)
            and type(other.trigger) is type(self.trigger)
            and other.trigger.config == self.trigger.config
            and len(other.reactions) == len(self.reactions)
            and all(
                type(other_reaction) is type(reaction) and other_reaction.config == reaction.config
                for reaction, other_reaction in zip(self.reactions, other.reactions)
            )
        )

    @classmethod
    @override
    def from_settings(cls, settings: dict, logger: logging.Logger) -> Self:
        config = RuleConfig.from_settings(settings)

        reactions_settings = settings.get("reactions")
        if (
            not isinstance(reactions_settings, list)
            or not reactions_settings
            or not all(isinstance(item, dict) for item in reactions_settings)
        ):
            msg = "reactions is not a list of at least one reaction"
            raise ValueError(msg)

        reactions = []
        for reaction_settings in reactions_settings:
            reaction_config = ReactionConfig.from_settings(reaction_settings)
            reactions.append(REACTIONS[reaction_config.reaction_type].from_settings(reaction_settings))

        trigger = TRIGGERS[config.trigger_type].from_settings(settings)
        return cls(config, trigger, conditions_from_settings(settings), reactions, logger)
