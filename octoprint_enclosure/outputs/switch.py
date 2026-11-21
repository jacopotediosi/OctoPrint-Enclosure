from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.settings import HexInt, setting
from octoprint_enclosure.utils import LabeledValue

from .config import OutputConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend


@dataclass(frozen=True)
class SwitchConfig(OutputConfig):
    """The configuration of an output with a switch, on a GPIO pin or driven by a device on the I2C bus."""

    gpio_i2c_enabled: bool = setting(
        label="Connection",
        choices=[LabeledValue(value=False, label="GPIO pin"), LabeledValue(value=True, label="I2C")],
    )
    """Whether the output switch is driven by a device on the I2C bus, instead of a GPIO pin."""

    gpio_pin: int = setting(
        label="GPIO",
        help_text="GPIO the output is connected to.",
        min_value=0,
        visible_if={"gpio_i2c_enabled": [False]},
    )
    """The GPIO pin of the output switch, when it isn't driven through I2C."""

    gpio_i2c_bus: int = setting(
        label="I2C Bus",
        help_text=(
            "1 is the bus of GPIO 2 and 3. For a device on another bus, for example one made on other pins with "
            "<code>dtoverlay=i2c-gpio</code>, use its number: <code>i2cdetect -l</code> lists the buses. I2C needs to "
            "be enabled: run <code>sudo raspi-config</code> and enable I2C in the interface options."
        ),
        min_value=0,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The number of the I2C bus."""

    gpio_i2c_address: HexInt = setting(
        label="I2C Address",
        help_text=(
            "Address of the device, in hexadecimal. Find it by running <code>i2cdetect -y 1</code> (from the "
            "<code>i2c-tools</code> package) on your Raspberry Pi."
        ),
        min_value=0,
        max_value=127,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The I2C address of the device."""

    gpio_i2c_register: HexInt = setting(
        label="I2C Register",
        help_text="Register to write, in hexadecimal.",
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The I2C register written to set the output switch high or low."""

    gpio_i2c_data_on: HexInt = setting(
        label="I2C ON data",
        help_text="Value written to turn the output on, in hexadecimal.",
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The value of the I2C registers when the output switch is high."""

    gpio_i2c_data_off: HexInt = setting(
        label="I2C OFF data",
        help_text="Value written to turn the output off, in hexadecimal.",
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The value written via I2C to set the output switch low."""

    gpio_i2c_register_status: HexInt = setting(
        label="I2C Register (read status)",
        help_text="Register read to know the state of the output, in hexadecimal.",
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The I2C register read to know whether the output switch is high."""

    active_low: bool = setting(
        label="Active Low",
        help_text="Enable it if your device turns on when the pin is connected to ground, as most relay modules do.",
    )
    """Whether the output switch is on when it is low."""


class Switch:
    """A switch that is either on or off, on a GPIO pin or driven by a device on the I2C bus."""

    _config: SwitchConfig
    """The configuration of the output with the switch."""

    _gpio: GpioBackend
    """The GPIO backend."""

    _i2c: I2cBackend
    """The I2C backend."""

    _logger: logging.Logger

    def __init__(self, config: SwitchConfig, gpio: GpioBackend, i2c: I2cBackend, logger: logging.Logger) -> None:
        """Set up the switch.

        Args:
            config (SwitchConfig): The configuration of the output with the switch.
            gpio (GpioBackend): The GPIO backend.
            i2c (I2cBackend): The I2C backend.
            logger (logging.Logger): The logger to write to.

        """
        self._config = config
        self._gpio = gpio
        self._i2c = i2c
        self._logger = logger

    @property
    def gpio_pins(self) -> frozenset[int]:
        """The GPIO pin of the switch, empty for a switch driven through I2C."""
        if self._config.gpio_i2c_enabled:
            return frozenset()
        return frozenset({self._config.gpio_pin})

    def setup(self) -> None:
        """Set up the pin of the switch.

        A switch driven through I2C has no pin, so nothing is set up.

        Raises:
            Exception: If the pin can't be set up.

        """
        config = self._config

        if config.gpio_i2c_enabled:
            return

        initial_value = self._gpio.HIGH if config.active_low else self._gpio.LOW
        self._logger.debug("Setting GPIO pin %s as OUTPUT with initial value: %s", config.gpio_pin, initial_value)
        self._gpio.setup(config.gpio_pin, self._gpio.OUT, initial=initial_value)

    def is_on(self) -> bool:
        """Read whether the switch is on.

        Returns:
            bool: Whether the switch is on.

        Raises:
            Exception: If the switch can't be read.

        """
        config = self._config

        if config.gpio_i2c_enabled:
            with self._i2c.SMBus(config.gpio_i2c_bus) as bus:
                data = bus.read_i2c_block_data(config.gpio_i2c_address, config.gpio_i2c_register_status, 1)
            self._logger.debug("Read %s from register %s", data, config.gpio_i2c_register_status)
            high = data[0] == config.gpio_i2c_data_on
        else:
            high = bool(self._gpio.input(config.gpio_pin))

        return high != config.active_low

    def set(self, *, on: bool) -> None:
        """Turn the switch on or off.

        Args:
            on (bool): Whether to turn the switch on or off.

        Raises:
            Exception: If the switch can't be written.

        """
        config = self._config
        high = on != config.active_low

        if config.gpio_i2c_enabled:
            data = config.gpio_i2c_data_on if high else config.gpio_i2c_data_off
            with self._i2c.SMBus(config.gpio_i2c_bus) as bus:
                bus.write_i2c_block_data(config.gpio_i2c_address, config.gpio_i2c_register, [data])
            self._logger.debug(
                "Writing on GPIO (i2c): %s/%s value %s",
                config.gpio_i2c_address,
                config.gpio_i2c_register,
                high,
            )
        else:
            self._gpio.output(config.gpio_pin, high)
            self._logger.debug("Writing on GPIO: %s value %s", config.gpio_pin, high)
