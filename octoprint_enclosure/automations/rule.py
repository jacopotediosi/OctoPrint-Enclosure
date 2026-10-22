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

    reaction_type: str = ""
    """The type of the reaction of the rule."""


class RuleAutomation(Automation[RuleConfig]):
    """An automation that reacts to a trigger."""

    config_class = RuleConfig

    _trigger: Trigger
    """What starts the rule."""

    reaction: Reaction
    """What the rule does."""

    def __init__(self, config: RuleConfig, trigger: Trigger, reaction: Reaction, logger: logging.Logger) -> None:
        """Set up the automation rule.

        Args:
            config (RuleConfig): The configuration of the automation rule.
            trigger (Trigger): What starts the automation rule.
            reaction (Reaction): What the automation rule does.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, logger)
        self._trigger = trigger
        self.reaction = reaction

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
            and type(other.reaction) is type(self.reaction)
            and other.reaction.config == self.reaction.config
        )

    @classmethod
    @override
    def from_settings(cls, settings: dict, logger: logging.Logger) -> Self:
        config = RuleConfig.from_settings(settings)

        trigger_class = TRIGGERS.get(config.trigger_type)
        if trigger_class is None:
            msg = f"Unsupported trigger type: {config.trigger_type!r}"
            raise ValueError(msg)

        reaction_class = REACTIONS.get(config.reaction_type)
        if reaction_class is None:
            msg = f"Unsupported reaction type: {config.reaction_type!r}"
            raise ValueError(msg)

        return cls(config, trigger_class.from_settings(settings), reaction_class.from_settings(settings), logger)
