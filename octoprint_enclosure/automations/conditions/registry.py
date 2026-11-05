from __future__ import annotations

from typing import TYPE_CHECKING

from .print_job import PrintJobCondition

if TYPE_CHECKING:
    from .base import Condition

CONDITIONS: dict[str, type[Condition]] = {
    "print_job": PrintJobCondition,
}
"""The supported types of automation conditions, by identifier."""
