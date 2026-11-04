from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.core import REQUIRED, BaseConfig, MeasurementType

from .base import Output
from .switch import Switch, SwitchConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend


class ThermostatDeviceType(Enum):
    """The type of the device a thermostat turns on and off."""

    HEATER = "heater"
    COOLER = "cooler"
    DEHUMIDIFIER = "dehumidifier"

    @property
    def measurement_type(self) -> MeasurementType:
        """What the device acts on: the humidity for a dehumidifier, the temperature for the others."""
        if self is ThermostatDeviceType.DEHUMIDIFIER:
            return MeasurementType.HUMIDITY
        return MeasurementType.TEMPERATURE


@dataclass(frozen=True)
class ThermostatConfig(SwitchConfig):
    """The configuration of a thermostat."""

    linked_temp_sensor: int = REQUIRED
    """The id of the input of the sensor that reads the temperature or the humidity."""

    temp_ctr_type: ThermostatDeviceType = REQUIRED
    """The type of the device that the output switch turns on and off."""

    temp_ctr_deadband: float = REQUIRED
    """How far below the target the value can go before a heater turns on, or a cooler turns off. Between there and
    the target, the device stays as it is. A dehumidifier ignores it."""

    temp_ctr_max_temp: float = REQUIRED
    """The temperature above which a heater turns its thermostat off, or 0 or less if it has no maximum."""


@dataclass(frozen=True)
class ThermostatSetpoint(BaseConfig):
    """The setpoint a thermostat is turned on to."""

    target: float = 0
    """The target temperature in Celsius, or the target humidity for a dehumidifier; 0 turns the thermostat off."""


class ThermostatOutput(Output[ThermostatConfig, ThermostatSetpoint]):
    """The output of a thermostat: the switch of its device, turned on and off as the thermostat decides."""

    config_class = ThermostatConfig
    setpoint_class = ThermostatSetpoint

    switch: Switch
    """The switch of the device of the thermostat."""

    def __init__(
        self,
        config: ThermostatConfig,
        gpio: GpioBackend,
        i2c: I2cBackend,
        logger: logging.Logger,
    ) -> None:
        """Set up the output.

        Args:
            config (ThermostatConfig): The configuration of the output.
            gpio (GpioBackend): The GPIO backend.
            i2c (I2cBackend): The I2C backend.
            logger (logging.Logger): The logger to write to.

        """
        super().__init__(config, gpio, i2c, logger)
        self.switch = Switch(config, gpio, i2c, logger)

    @property
    @override
    def gpio_pins(self) -> frozenset[int]:
        return self.switch.gpio_pins

    @override
    def setup(self) -> None:
        self.switch.setup()

    @override
    def is_on(self) -> bool:
        """Read whether the device of the thermostat is on.

        Returns:
            bool: Whether the device is on.

        Raises:
            Exception: If the switch can't be read.

        """
        return self.switch.is_on()

    @override
    def turn_off(self) -> None:
        """Turn the device off.

        Raises:
            Exception: If the switch can't be written.

        """
        self.switch.set(on=False)

    @override
    def run_enc_command(self, command: str) -> None:
        return None


class ThermostatStatus(Enum):
    """What a thermostat is doing."""

    ON = "on"
    """The device is on, to reach the target."""

    IDLE = "idle"
    """The device is off, because the target is reached or the thermostat is off."""

    NO_READING = "no_reading"
    """The linked sensor reading failed, so a cooler is on, and a heater or a dehumidifier is off."""


class Thermostat:
    """Decides when its device has to be on, to keep a temperature or a humidity at a target.

    The device (e.g., a heater/cooler/dehumidifier) is wired to the switch of the thermostat output, and the
    thermostat never touches it: asked with a new reading of its sensor, it answers whether the device has to be on,
    and who asks does the switching.
    """

    setpoint_class = ThermostatSetpoint

    _config: ThermostatConfig

    _target: float
    """The target temperature or humidity, or 0 if the thermostat is off."""

    _status: ThermostatStatus
    """What the thermostat is doing."""

    _was_on: bool
    """Whether the device had to be on at the last decision."""

    def __init__(self, config: ThermostatConfig) -> None:
        """Set up the thermostat, with no target.

        Args:
            config (ThermostatConfig): The configuration of the thermostat.

        """
        self._config = config

        self._target = 0.0
        self._status = ThermostatStatus.IDLE
        self._was_on = False

    @property
    def config(self) -> ThermostatConfig:
        """The configuration of the output of the thermostat."""
        return self._config

    @property
    def target(self) -> float:
        """The target temperature or humidity, or 0 if the thermostat is off."""
        return self._target

    @property
    def status(self) -> ThermostatStatus:
        """What the thermostat is doing."""
        return self._status

    def set_target(self, target: float) -> None:
        """Set the target temperature or humidity.

        Args:
            target (float): The target temperature or humidity, or 0 to turn the thermostat off.

        """
        self._target = target

    def is_on(self) -> bool:
        """Tell whether the thermostat has a target."""
        return self._target != 0

    def turn_on(self, setpoint: ThermostatSetpoint) -> None:
        """Set the target temperature or humidity.

        Args:
            setpoint (ThermostatSetpoint): The target.

        """
        self._target = setpoint.target

    def turn_off(self) -> None:
        """Set the target to 0."""
        self._target = 0.0

    def is_above_max_temp(self, temperature: float | None) -> bool:
        """Tell whether a heater has gone above its maximum temperature.

        Args:
            temperature (float | None): The temperature read by the sensor, or None if it has none.

        Returns:
            bool: Whether the device is a heater with a maximum temperature, the thermostat is on and the temperature
                is above the maximum.

        """
        config = self._config
        return (
            config.temp_ctr_type is ThermostatDeviceType.HEATER
            and self._target != 0
            and temperature is not None
            and 0 < config.temp_ctr_max_temp < temperature
        )

    def decide(self, temperature: float | None, humidity: float | None) -> bool:
        """Decide whether the device has to be on after a new reading of the sensor, to keep the target.

        Args:
            temperature (float | None): The temperature read by the sensor, or None if it has none.
            humidity (float | None): The humidity read by the sensor, or None if it has none.

        Returns:
            bool: Whether the device has to be on.

        """
        config = self._config

        # Determine whether to consider humidity or temperature, depending on the device type
        if config.temp_ctr_type is ThermostatDeviceType.DEHUMIDIFIER:
            read_value, deadband = humidity, 0.0
        else:
            read_value, deadband = temperature, config.temp_ctr_deadband

        # Update the status
        if self._target == 0:
            status = ThermostatStatus.IDLE
        elif read_value is None:
            status = ThermostatStatus.NO_READING
        elif self._target - deadband <= read_value <= self._target:
            # Between the target minus the deadband and the target, the device stays as it is
            status = ThermostatStatus.ON if self._was_on else ThermostatStatus.IDLE
        elif config.temp_ctr_type is ThermostatDeviceType.HEATER:
            status = ThermostatStatus.ON if read_value < self._target else ThermostatStatus.IDLE
        else:
            status = ThermostatStatus.ON if read_value > self._target else ThermostatStatus.IDLE
        self._status = status

        # Decide if the device should be on
        should_be_on = status is ThermostatStatus.ON
        # Without a reading, a cooler stays on, so the temperature can't go up
        if status is ThermostatStatus.NO_READING and config.temp_ctr_type is ThermostatDeviceType.COOLER:
            should_be_on = True
        self._was_on = should_be_on

        return should_be_on
