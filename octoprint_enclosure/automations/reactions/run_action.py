from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.settings import ActionId, BaseConfig, setting

from .base import Reaction


@dataclass(frozen=True)
class RunActionConfig(BaseConfig):
    """The configuration of an automation reaction that runs an action."""

    action: ActionId = setting(
        label="Action",
        help_text="Action to run when the event happens. Configured in the Actions tab.",
    )
    """The id of the action."""


class RunActionReaction(Reaction[RunActionConfig]):
    """An automation reaction that runs an action."""

    config_class = RunActionConfig
