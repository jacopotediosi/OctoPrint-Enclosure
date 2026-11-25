from __future__ import annotations

from octoprint_enclosure.utils import check_all_members_mapped

from .config import InputType
from .gpio import GpioInputs
from .sensors import Sensors

INPUTS: dict[InputType, type[GpioInputs | Sensors]] = {
    InputType.GPIO: GpioInputs,
    InputType.TEMPERATURE_SENSOR: Sensors,
}
"""The class implementing each type of input."""

# Check that INPUTS contains every type of input
check_all_members_mapped(INPUTS, InputType)
