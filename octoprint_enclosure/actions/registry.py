from __future__ import annotations

from typing import TYPE_CHECKING

from octoprint_enclosure.utils import check_all_members_mapped

from .base import ActionType
from .gcode import GcodeAction
from .printer import PrinterAction
from .shell import ShellAction

if TYPE_CHECKING:
    from .base import Action

ACTIONS: dict[ActionType, type[Action]] = {
    ActionType.GCODE: GcodeAction,
    ActionType.SHELL: ShellAction,
    ActionType.PRINTER: PrinterAction,
}
"""The class implementing each type of action."""

# Check that ACTIONS contains every type of action
check_all_members_mapped(ACTIONS, ActionType)
