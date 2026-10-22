from __future__ import annotations

from typing import TYPE_CHECKING

from .output_control import OutputControlReaction
from .run_action import RunActionReaction
from .stop_temp_hum_control import StopTempHumControlReaction

if TYPE_CHECKING:
    from .base import Reaction

REACTIONS: dict[str, type[Reaction]] = {
    "output_control": OutputControlReaction,
    "run_action": RunActionReaction,
    "stop_temp_hum_control": StopTempHumControlReaction,
}
"""The supported types of automation reactions, by identifier."""
