from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .gcode import GcodeAction
from .printer import PrinterAction
from .shell import ShellAction

if TYPE_CHECKING:
    from .base import Action


@dataclass(frozen=True)
class ActionDefinition:
    """Describes a type of action."""

    label: str
    """The name of the type of action."""

    implementation: type[Action]
    """The class implementing the action."""


ACTIONS: dict[str, ActionDefinition] = {
    "gcode_output": ActionDefinition(label="Gcode", implementation=GcodeAction),
    "shell_output": ActionDefinition(label="Shell Script", implementation=ShellAction),
    "printer": ActionDefinition(label="Printer", implementation=PrinterAction),
}
"""The supported types of actions, by identifier."""
