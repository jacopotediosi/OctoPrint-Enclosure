from __future__ import annotations

from typing import TYPE_CHECKING

from .ledstrip import LedstripOutput
from .neopixel_direct import NeopixelDirectOutput
from .neopixel_indirect import NeopixelIndirectOutput
from .pwm import PwmOutput
from .regular import RegularOutput

if TYPE_CHECKING:
    from .base import Output

OUTPUTS: dict[str, type[Output]] = {
    "ledstrip": LedstripOutput,
    "neopixel_direct": NeopixelDirectOutput,
    "neopixel_indirect": NeopixelIndirectOutput,
    "pwm": PwmOutput,
    "regular": RegularOutput,
    "temp_hum_control": RegularOutput,
}
"""The supported types of outputs, by identifier."""
