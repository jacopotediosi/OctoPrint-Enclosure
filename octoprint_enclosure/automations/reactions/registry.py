from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .output_control import OutputControlReaction
from .run_action import RunActionReaction

if TYPE_CHECKING:
    from .base import Reaction


@dataclass(frozen=True)
class ReactionDefinition:
    """Describes a type of automation reaction."""

    label: str
    """The name of the type of reaction."""

    implementation: type[Reaction]
    """The class implementing the reaction."""


REACTIONS: dict[str, ReactionDefinition] = {
    "output_control": ReactionDefinition(label="Output Control", implementation=OutputControlReaction),
    "run_action": ReactionDefinition(label="Run Action", implementation=RunActionReaction),
}
"""The supported types of automation reactions, by identifier."""
