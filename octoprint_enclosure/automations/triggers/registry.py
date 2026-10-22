from __future__ import annotations

from typing import TYPE_CHECKING

from .gpio_input import GpioInputTrigger
from .temperature import TemperatureTrigger

if TYPE_CHECKING:
    from .base import Trigger

TRIGGERS: dict[str, type[Trigger]] = {
    "gpio_input": GpioInputTrigger,
    "temperature": TemperatureTrigger,
}
"""The supported types of automation triggers, by identifier."""
