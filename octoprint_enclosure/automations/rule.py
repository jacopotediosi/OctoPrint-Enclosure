from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.utils import parse_hhmm, seconds_until_next

from .base import Automation, AutomationConfig
from .conditions import conditions_from_settings
from .reactions import REACTIONS, OutputControlReaction, OutputSetState
from .triggers import TRIGGERS

if TYPE_CHECKING:
    import logging

    from typing_extensions import Self

    from octoprint_enclosure.outputs import OutputSetpointConfig
    from octoprint_enclosure.settings import BaseConfig, OutputId

    from .conditions import Condition
    from .reactions.base import Reaction
    from .triggers.base import Trigger


@dataclass(frozen=True)
class RuleConfig(AutomationConfig):
    """The configuration of an automation rule."""

    trigger_type: str = ""
    """The type of the trigger of the rule."""

    delay: float = 0
    """The seconds to wait after the trigger before running the reactions."""

    at: str = ""
    """The time of day, as HH:MM, at which to run the reactions."""

    def __post_init__(self) -> None:
        """Check the rule config correctness.

        Raises:
            ValueError: If the delay is negative, the time of day is not HH:MM, or both are set.

        """
        problems = []
        if self.delay < 0:
            problems.append("delay must be 0 or more")
        if self.at and parse_hhmm(self.at) is None:
            problems.append("at must be a time of day as HH:MM")
        if self.delay and self.at:
            problems.append("delay and at can't both be set")
        if problems:
            msg = "; ".join(problems)
            raise ValueError(msg)

    def delay_seconds(self) -> float:
        """Get how long to wait before running the reactions, from now.

        Returns:
            float: The seconds to wait before running the reactions.

        """
        time_of_day = parse_hhmm(self.at)
        return self.delay if time_of_day is None else seconds_until_next(time_of_day)


class RuleAutomation(Automation[RuleConfig]):
    """An automation that reacts to a trigger, with one or more reactions, when its conditions are satisfied."""

    config_class = RuleConfig

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

        trigger_class = TRIGGERS.get(config.trigger_type)
        if trigger_class is None:
            msg = f"Unsupported trigger type: {config.trigger_type!r}"
            raise ValueError(msg)

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
            reaction_type = reaction_settings.get("reaction_type", "")
            reaction_class = REACTIONS.get(reaction_type)
            if reaction_class is None:
                msg = f"Unsupported reaction type: {reaction_type!r}"
                raise ValueError(msg)
            reactions.append(reaction_class.from_settings(reaction_settings))

        return cls(config, trigger_class.from_settings(settings), conditions_from_settings(settings), reactions, logger)
