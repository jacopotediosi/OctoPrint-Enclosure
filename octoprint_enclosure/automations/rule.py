from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Automation
from .reactions import REACTIONS
from .triggers import TRIGGERS

if TYPE_CHECKING:
    import logging

    from typing_extensions import Self

    from .reactions.base import Reaction
    from .triggers.base import Trigger


@dataclass(frozen=True)
class RuleConfig(BaseConfig):
    """The configuration of an automation rule."""

    trigger_type: str = ""
    """The type of the trigger of the rule."""


class RuleAutomation(Automation[RuleConfig]):
    """An automation that reacts to a trigger, with one or more reactions."""

    config_class = RuleConfig

    _trigger: Trigger
    """What starts the rule."""

    reactions: list[Reaction]
    """What the rule does, in order."""

    def __init__(
        self,
        config: RuleConfig,
        trigger: Trigger,
        reactions: list[Reaction],
        logger: logging.Logger,
    ) -> None:
        """Set up the automation rule.

        Args:
            config (RuleConfig): The configuration of the automation rule.
            trigger (Trigger): What starts the automation rule.
            reactions (list[Reaction]): What the automation rule does, in order.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, logger)
        self._trigger = trigger
        self.reactions = reactions

    @property
    @override
    def trigger(self) -> Trigger:
        """What starts the rule."""
        return self._trigger

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

        return cls(config, trigger_class.from_settings(settings), reactions, logger)
