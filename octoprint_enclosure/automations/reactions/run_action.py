from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.config import ActionId, config_field
from octoprint_enclosure.utils import N_

from .base import Reaction, ReactionConfig


@dataclass(frozen=True)
class RunActionConfig(ReactionConfig):
    """The configuration of an automation reaction that runs an action."""

    action: ActionId = config_field(
        label=N_("Action"),
        help_text=N_("Action to run when the event happens. Configured in the Actions tab."),
    )
    """The id of the action."""


class RunActionReaction(Reaction[RunActionConfig]):
    """An automation reaction that runs an action."""

    config_class = RunActionConfig
