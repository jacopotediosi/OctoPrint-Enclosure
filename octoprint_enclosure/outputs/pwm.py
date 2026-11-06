from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.settings import REQUIRED, BaseConfig
from octoprint_enclosure.utils import clamp, get_gcode_param, to_int

from .base import Output, OutputError
from .config import OutputConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, GpioPwm, I2cBackend


@dataclass(frozen=True)
class PwmConfig(OutputConfig):
    """The configuration of a PWM output."""

    gpio_pin: int = REQUIRED
    """The GPIO pin of the PWM."""

    pwm_frequency: int = REQUIRED
    """The frequency of the PWM, in Hz."""


@dataclass(frozen=True)
class PwmSetpoint(BaseConfig):
    """The setpoint a PWM output is turned on to."""

    duty_cycle: float = 0
    """The duty cycle, from 0 to 100."""

    def __post_init__(self) -> None:
        """Check the duty cycle.

        Raises:
            ValueError: If the duty cycle is not between 0 and 100.

        """
        if not 0 <= self.duty_cycle <= 100:
            msg = f"duty_cycle must be between 0 and 100, not {self.duty_cycle}"
            raise ValueError(msg)


class PwmOutput(Output[PwmConfig, PwmSetpoint]):
    """An output driven by software PWM on a GPIO pin."""

    config_class = PwmConfig
    setpoint_class = PwmSetpoint

    _pwm: GpioPwm | None
    """The PWM of the GPIO backend, or None if it isn't started."""

    _duty_cycle: float
    """The duty cycle of the PWM, from 0 to 100."""

    def __init__(self, config: PwmConfig, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        super().__init__(config, gpio, i2c, logger)
        self._pwm = None
        self._duty_cycle = 0

    @property
    def duty_cycle(self) -> float:
        """The duty cycle of the PWM, from 0 to 100."""
        return self._duty_cycle

    @property
    @override
    def gpio_pins(self) -> frozenset[int]:
        return frozenset({self.config.gpio_pin})

    @override
    def setup(self) -> None:
        """Set up the pin and start the PWM, off.

        Raises:
            Exception: If the PWM can't be started.

        """
        pin = self.config.gpio_pin
        self._logger.debug("Starting PWM on pin %s at %s Hz", pin, self.config.pwm_frequency)

        self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.LOW)
        pwm = self._gpio.PWM(pin, self.config.pwm_frequency)
        pwm.start(0)
        self._pwm = pwm

    @override
    def release(self) -> None:
        """Stop the PWM."""
        if self._pwm is not None:
            self._pwm.stop()
            self._pwm = None

    @override
    def is_on(self) -> bool:
        """Tell whether the duty cycle of the PWM is above 0."""
        return self._duty_cycle > 0

    def turn_on(self, setpoint: PwmSetpoint) -> None:
        """Set the duty cycle of the PWM.

        Args:
            setpoint (PwmSetpoint): The duty cycle.

        Raises:
            OutputError: If the PWM isn't started.
            Exception: If the duty cycle can't be written.

        """
        self._set_duty_cycle(setpoint.duty_cycle)

    @override
    def turn_off(self) -> None:
        """Set the duty cycle of the PWM to 0.

        Raises:
            OutputError: If the PWM isn't started.
            Exception: If the duty cycle can't be written.

        """
        self._set_duty_cycle(0.0)

    def _set_duty_cycle(self, duty_cycle: float) -> None:
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

        self.turn_on(PwmSetpoint(duty_cycle))

        return f"Setting PWM output {index_id} to value {duty_cycle}"
