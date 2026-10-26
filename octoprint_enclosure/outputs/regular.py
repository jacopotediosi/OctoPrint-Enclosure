from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from typing_extensions import override

from octoprint_enclosure.utils import clamp, get_gcode_param, to_int

from .switch import SwitchConfig, SwitchOutput


class RegularSetState(Enum):
    """What to do with a regular output: turn it on or off, or toggle it."""

    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"


@dataclass(frozen=True)
class RegularConfig(SwitchConfig):
    """The configuration of a regular output."""


class RegularOutput(SwitchOutput[RegularConfig]):
    """An output that is either on or off, on a GPIO pin or driven by a device on the I2C bus."""

    config_class = RegularConfig

    def turn_on(self) -> None:
        """Turn the output on.

        Raises:
            Exception: If the output can't be written.

        """
        self._switch(on=True)

    @override
    def turn_off(self) -> None:
        """Turn the output off.

        Raises:
            Exception: If the output can't be written.

        """
        self._switch(on=False)

    def toggle(self) -> bool:
        """Turn the output off if it is on, and on if it is off.

        Returns:
            bool: Whether the output is now on.

        Raises:
            Exception: If the output can't be read or written.

        """
        on = not self.is_on()
        self._switch(on=on)
        return on

    @override
    def run_enc_command(self, command: str) -> str:
        index_id = to_int(get_gcode_param(command, "O"))
        on = clamp(to_int(get_gcode_param(command, "S")), 0, 1) == 1

        if on:
            self.turn_on()
        else:
            self.turn_off()

        return f"Setting REGULAR output {index_id} to value {on}"
