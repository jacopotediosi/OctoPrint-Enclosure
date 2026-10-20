from __future__ import annotations

from typing import TYPE_CHECKING

from .filament import FilamentAutomation
from .rule import RuleAutomation

if TYPE_CHECKING:
    from .base import Automation

AUTOMATIONS: dict[str, type[Automation]] = {
    "rule": RuleAutomation,
    "filament": FilamentAutomation,
}
"""The supported types of automations, by identifier."""
