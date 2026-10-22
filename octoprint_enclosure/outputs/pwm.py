from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.utils import clamp, get_gcode_param, to_int

from .base import Output, OutputError

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, GpioPwm, I2cBackend


@dataclass(frozen=True)
class PwmConfig(BaseConfig):
    """The configuration of a PWM output."""

    gpio_pin: int
    """The GPIO pin of the PWM."""

    pwm_frequency: int
    """The frequency of the PWM, in Hz."""

    default_duty_cycle: int = 0
    """The duty cycle the PWM starts with, from 0 to 100."""


class PwmOutput(Output[PwmConfig]):
    """An output driven by software PWM on a GPIO pin."""

    config_class = PwmConfig

    _pwm: GpioPwm | None
    """The PWM of the GPIO backend, or None if it isn't started."""

    _duty_cycle: float
    """The duty cycle of the PWM, from 0 to 100."""

    def __init__(self, config: PwmConfig, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        super().__init__(config, gpio, i2c, logger)
        self._pwm = None
        self._duty_cycle = config.default_duty_cycle

    @property
    def duty_cycle(self) -> float:
        """The duty cycle of the PWM, from 0 to 100."""
        return self._duty_cycle

    def start(self) -> None:
        """Set up the pin and start the PWM with the default duty cycle.

        Raises:
            Exception: If the PWM can't be started.

        """
        if self._pwm is not None:
            return

        pin = self.config.gpio_pin
        self._logger.debug("Starting PWM on pin %s at %s Hz", pin, self.config.pwm_frequency)

        self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.LOW)
        pwm = self._gpio.PWM(pin, self.config.pwm_frequency)
        pwm.start(self.config.default_duty_cycle)
        self._pwm = pwm

    def stop(self) -> None:
        """Stop the PWM."""
        if self._pwm is not None:
            self._pwm.stop()
            self._pwm = None

    def set_duty_cycle(self, duty_cycle: float) -> None:
        """Set the duty cycle of the PWM.

        Args:
            duty_cycle (float): The duty cycle, from 0 to 100.

        Raises:
            OutputError: If the PWM isn't started.
            Exception: If the duty cycle can't be written.

        """
        if self._pwm is None:
            msg = "The PWM is not started"
            raise OutputError(msg)

        if int(duty_cycle) == int(self._duty_cycle):
            return

        self._pwm.ChangeDutyCycle(duty_cycle)
        self._duty_cycle = duty_cycle
        self._logger.debug("Writing PWM on gpio: %s value %s", self.config.gpio_pin, duty_cycle)

    @override
    def run_enc_command(self, command: str) -> str:
        index_id = to_int(get_gcode_param(command, "O"))
        duty_cycle = clamp(to_int(get_gcode_param(command, "S")), 0, 100)

        self.set_duty_cycle(duty_cycle)

        return f"Setting PWM output {index_id} to value {duty_cycle}"
