from __future__ import annotations

from typing import TYPE_CHECKING

from .output_control import OutputControlReaction
from .printer_control import PrinterControlReaction
from .run_action import RunActionReaction

if TYPE_CHECKING:
    from .base import Reaction

REACTIONS: dict[str, type[Reaction]] = {
    "output_control": OutputControlReaction,
    "run_action": RunActionReaction,
    "printer_control": PrinterControlReaction,
}
"""The supported types of automation reactions, by identifier."""
