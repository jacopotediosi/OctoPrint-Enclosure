from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.settings import REQUIRED, ActionId, BaseConfig

from .base import Reaction


@dataclass(frozen=True)
class RunActionConfig(BaseConfig):
    """The configuration of an automation reaction that runs an action."""

    action: ActionId = REQUIRED
    """The id of the action."""


class RunActionReaction(Reaction[RunActionConfig]):
    """An automation reaction that runs an action."""

    config_class = RunActionConfig
