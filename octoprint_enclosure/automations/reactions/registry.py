from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import check_all_members_mapped

from .base import ReactionType
from .output_control import OutputControlReaction
from .run_action import RunActionReaction

if TYPE_CHECKING:
    from .base import Reaction

REACTIONS: dict[ReactionType, type[Reaction]] = {
    ReactionType.OUTPUT_CONTROL: OutputControlReaction,
    ReactionType.RUN_ACTION: RunActionReaction,
}
"""The class implementing each type of automation reaction."""

# Check that REACTIONS contains every type of automation reaction
check_all_members_mapped(REACTIONS, ReactionType)
