from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.settings import BaseConfig
from octoprint_enclosure.utils import clamp, get_gcode_param

from .base import Output
from .switch import Switch, SwitchConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend


@dataclass(frozen=True)
class RegularConfig(SwitchConfig):
    """The configuration of a regular output."""


@dataclass(frozen=True)
class RegularSetpoint(BaseConfig):
    """The setpoint a regular output is turned on to."""


class RegularOutput(Output[RegularConfig, RegularSetpoint]):
    """An output that is either on or off, on a GPIO pin or driven by a device on the I2C bus."""

    config_class = RegularConfig
    setpoint_class = RegularSetpoint

    _switch: Switch
    """The switch of the output."""

    def __init__(self, config: RegularConfig, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        """Set up the output.

        Args:
            config (RegularConfig): The configuration of the output.
            gpio (GpioBackend): The GPIO backend.
            i2c (I2cBackend): The I2C backend.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, gpio, i2c, logger)
        self._switch = Switch(config, gpio, i2c, logger)

    @property
    @override
    def gpio_pins(self) -> frozenset[int]:
        return self._switch.gpio_pins

    @override
    def setup(self) -> None:
        self._switch.setup()

    @override
    def is_on(self) -> bool:
        return self._switch.is_on()

    def turn_on(self, setpoint: RegularSetpoint) -> None:
        """Turn the output on.

        Args:
            setpoint (RegularSetpoint): Nothing: the output is just on.

        Raises:
            Exception: If the output switch can't be written.

        """
        self._switch.set(on=True)

    @override
    def turn_off(self) -> None:
        self._switch.set(on=False)

    @override
    def run_enc_command(self, command: str) -> str:
        on = clamp(int(get_gcode_param(command, "S")), 0, 1) == 1

        self._switch.set(on=on)

        return f"Setting REGULAR output {self.config.index_id} to value {on}"
