from __future__ import annotations

from typing import TYPE_CHECKING

from .gcode import GcodeAction
from .printer import PrinterAction
from .shell import ShellAction

if TYPE_CHECKING:
    from .base import Action

ACTIONS: dict[str, type[Action]] = {
    "gcode_output": GcodeAction,
    "shell_output": ShellAction,
    "printer": PrinterAction,
}
"""The supported types of actions, by identifier."""
