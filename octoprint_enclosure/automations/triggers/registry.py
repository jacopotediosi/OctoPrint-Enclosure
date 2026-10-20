from __future__ import annotations

from typing import TYPE_CHECKING

from .gpio_input import GpioInputTrigger

if TYPE_CHECKING:
    from .base import Trigger

TRIGGERS: dict[str, type[Trigger]] = {
    "gpio_input": GpioInputTrigger,
}
"""The supported types of automation triggers, by identifier."""
