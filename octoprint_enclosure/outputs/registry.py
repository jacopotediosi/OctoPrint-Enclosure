from __future__ import annotations

from typing import TYPE_CHECKING

from .config import OutputType
from .ledstrip import LedstripOutput
from .neopixel_direct import NeopixelDirectOutput
from .neopixel_indirect import NeopixelIndirectOutput
from .pwm import PwmOutput
from .regular import RegularOutput
from .thermostat import ThermostatOutput

if TYPE_CHECKING:
    from .base import Output

OUTPUTS: dict[OutputType, type[Output]] = {
    OutputType.REGULAR: RegularOutput,
    OutputType.PWM: PwmOutput,
    OutputType.NEOPIXEL_INDIRECT: NeopixelIndirectOutput,
    OutputType.NEOPIXEL_DIRECT: NeopixelDirectOutput,
    OutputType.LEDSTRIP: LedstripOutput,
    OutputType.THERMOSTAT: ThermostatOutput,
}
"""The class of each type of output."""
