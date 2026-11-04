from __future__ import annotations

from typing import TYPE_CHECKING

from .output_control import OutputControlReaction
from .run_action import RunActionReaction

if TYPE_CHECKING:
    from .base import Reaction

REACTIONS: dict[str, type[Reaction]] = {
    "output_control": OutputControlReaction,
    "run_action": RunActionReaction,
}
"""The supported types of automation reactions, by identifier."""
