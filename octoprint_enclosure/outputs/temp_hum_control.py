from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from typing_extensions import override

from .switch import SwitchConfig, SwitchOutput

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend


class TempHumControlType(Enum):
    """What a temperature or humidity control drives."""

    HEATER = "heater"
    COOLER = "cooler"
    DEHUMIDIFIER = "dehumidifier"


@dataclass(frozen=True)
class TempHumControlConfig(SwitchConfig):
    """The configuration of an output that turns a device on and off to keep a temperature or a humidity at a target."""

    linked_temp_sensor: int
    """The id of the input of the sensor that reads the temperature or the humidity."""

    temp_ctr_type: TempHumControlType
    """The type of the device that the output switch turns on and off."""

    temp_ctr_deadband: float
    """How far below the target the value can go before a heater turns on, or a cooler turns off. Between there and
    the target, the device stays as it is. A dehumidifier ignores it."""

    temp_ctr_max_temp: float
    """The temperature above which a heater turns its control off, or 0 or less if it has no maximum."""


class TempHumControlStatus(Enum):
    """What a temperature or humidity control is doing."""

    ON = "on"
    """The device is on, to reach the target."""

    IDLE = "idle"
    """The device is off, because the target is reached or the control is off."""

    NO_READING = "no_reading"
    """The linked sensor reading failed, so a cooler is on, and a heater or a dehumidifier is off."""


class TempHumControlOutput(SwitchOutput[TempHumControlConfig]):
    """An output that turns a device on and off to keep a temperature or a humidity at a target."""

    config_class = TempHumControlConfig

    _target: float
    """The target temperature or humidity, or 0 if the control is off."""

    _status: TempHumControlStatus
    """What the control is doing."""

    def __init__(
        self,
        config: TempHumControlConfig,
        gpio: GpioBackend,
        i2c: I2cBackend,
        logger: logging.Logger,
    ) -> None:
        """Set up the temperature or humidity output control.

        Args:
            config (TempHumControlConfig): The configuration of the output control.
            gpio (GpioBackend): The GPIO backend.
            i2c (I2cBackend): The I2C backend.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, gpio, i2c, logger)
        self._target = 0.0
        self._status = TempHumControlStatus.IDLE

    @property
    def target(self) -> float:
        """The target temperature or humidity, or 0 if the control is off."""
        return self._target

    @property
    def status(self) -> TempHumControlStatus:
        """What the control is doing."""
        return self._status

    def set_target(self, target: float) -> None:
        """Set the target temperature or humidity.

        Args:
            target (float): The target temperature or humidity, or 0 to turn the control off.

        """
        self._target = target

    @override
    def turn_off(self) -> None:
        """Turn the control off: drop the target and switch the device off.

        Raises:
            Exception: If the output can't be regulated.

        """
        self.set_target(0.0)
        self.regulate(None, None)

    def regulate(self, temperature: float | None, humidity: float | None) -> TempHumControlStatus:
        """Turn the device on or off after a new reading of the sensor, to keep the target.

        Args:
            temperature (float | None): The temperature read by the sensor, or None if it has none.
            humidity (float | None): The humidity read by the sensor, or None if it has none.

        Returns:
            TempHumControlStatus: What the control is doing after the regulation.

        Raises:
            Exception: If the output can't be regulated.

        """
        config = self.config
        is_switch_on = self.is_on()

        # Handle heater above its maximum temperature
        if (
            config.temp_ctr_type is TempHumControlType.HEATER
            and self._target != 0
            and temperature is not None
            and 0 < config.temp_ctr_max_temp < temperature
        ):
            self._logger.warning("Maximum temperature reached")
            self._target = 0.0

        # Determine whether to consider humidity or temperature, depending on the control type
        if config.temp_ctr_type is TempHumControlType.DEHUMIDIFIER:
            read_value, deadband = humidity, 0.0
        else:
            read_value, deadband = temperature, config.temp_ctr_deadband

        # Update the status
        if self._target == 0:
            status = TempHumControlStatus.IDLE
        elif read_value is None:
            status = TempHumControlStatus.NO_READING
        elif self._target - deadband <= read_value <= self._target:
            # Between the target minus the deadband and the target, the device stays as it is
            status = TempHumControlStatus.ON if is_switch_on else TempHumControlStatus.IDLE
        elif config.temp_ctr_type is TempHumControlType.HEATER:
            status = TempHumControlStatus.ON if read_value < self._target else TempHumControlStatus.IDLE
        else:
            status = TempHumControlStatus.ON if read_value > self._target else TempHumControlStatus.IDLE
        self._status = status

        # Decide if the device should be on
        should_be_on = status is TempHumControlStatus.ON
        # Without a reading, a cooler stays on, so the temperature can't go up
        if status is TempHumControlStatus.NO_READING and config.temp_ctr_type is TempHumControlType.COOLER:
            should_be_on = True

        # Switch on or off
        if should_be_on != is_switch_on:
            self._logger.debug("Turning gpio to control temperature %s.", "on" if should_be_on else "off")
            self._switch(on=should_be_on)

        # Return status
        return status

    @override
    def run_enc_command(self, command: str) -> None:
        return None
