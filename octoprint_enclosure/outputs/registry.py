from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING

from .config import OutputType
from .ledstrip import LedstripOutput
from .neopixel_direct import NeopixelDirectOutput
from .neopixel_indirect import NeopixelIndirectOutput
from .pwm import PwmOutput
from .regular import RegularOutput
from .setpoint import OutputSetpointConfig
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

# Check that OutputSetpointConfig contains every field of every output setpoint
_output_setpoint_config_fields = {field.name for field in fields(OutputSetpointConfig)}
for _output_class in OUTPUTS.values():
    for _field in fields(_output_class.setpoint_class):
        if _field.name not in _output_setpoint_config_fields:
            msg = f"OutputSetpointConfig lacks the field {_field.name} of {_output_class.setpoint_class.__name__}"
            raise TypeError(msg)
