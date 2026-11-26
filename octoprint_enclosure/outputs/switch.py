from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from octoprint_enclosure.config import HexInt, config_field
from octoprint_enclosure.utils import N_, LabeledValue

from .config import OutputConfig

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.hardware import GpioBackend, I2cBackend


@dataclass(frozen=True)
class SwitchConfig(OutputConfig):
    """The configuration of an output with a switch, on a GPIO pin or driven by a device on the I2C bus."""

    gpio_i2c_enabled: bool = config_field(
        default=False,
        label=N_("Connection"),
        choices=[LabeledValue(value=False, label=N_("GPIO pin")), LabeledValue(value=True, label="I2C")],
    )
    """Whether the output switch is driven by a device on the I2C bus, instead of a GPIO pin."""

    gpio_pin: Optional[int] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and int | None fails on Python < 3.10
        label=N_("GPIO"),
        help_text=N_("GPIO the output is connected to."),
        min_value=0,
        visible_if={"gpio_i2c_enabled": [False]},
    )
    """The GPIO pin of the output switch, or None if it is driven through I2C."""

    gpio_i2c_bus: Optional[int] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and int | None fails on Python < 3.10
        default=1,
        label=N_("I2C Bus"),
        help_text=N_(
            "1 is the bus of GPIO 2 and 3. For a device on another bus, for example one made on other pins with "
            "<code>dtoverlay=i2c-gpio</code>, use its number: <code>i2cdetect -l</code> lists the buses. I2C needs to "
            "be enabled: run <code>sudo raspi-config</code> and enable I2C in the interface options.",
        ),
        min_value=0,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The number of the I2C bus, or None if the output switch is on a GPIO pin."""

    gpio_i2c_address: Optional[HexInt] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and HexInt | None fails on Python < 3.10
        label=N_("I2C Address"),
        help_text=N_(
            "Address of the device, in hexadecimal. Find it by running <code>i2cdetect -y 1</code> (from the "
            "<code>i2c-tools</code> package) on your Raspberry Pi.",
        ),
        min_value=0,
        max_value=127,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The I2C address of the device, or None if the output switch is on a GPIO pin."""

    gpio_i2c_register: Optional[HexInt] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and HexInt | None fails on Python < 3.10
        label=N_("I2C Register"),
        help_text=N_("Register to write, in hexadecimal."),
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The I2C register written to set the output switch high or low, or None if it is on a GPIO pin."""

    gpio_i2c_data_on: Optional[HexInt] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and HexInt | None fails on Python < 3.10
        label=N_("I2C ON data"),
        help_text=N_("Value written to turn the output on, in hexadecimal."),
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The value of the I2C registers when the output switch is high, or None if it is on a GPIO pin."""

    gpio_i2c_data_off: Optional[HexInt] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and HexInt | None fails on Python < 3.10
        label=N_("I2C OFF data"),
        help_text=N_("Value written to turn the output off, in hexadecimal."),
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The value written via I2C to set the output switch low, or None if it is on a GPIO pin."""

    gpio_i2c_register_status: Optional[HexInt] = config_field(  # noqa: UP045 - BaseConfig.from_settings evaluates, and HexInt | None fails on Python < 3.10
        label=N_("I2C Register (read status)"),
        help_text=N_("Register read to know the state of the output, in hexadecimal."),
        min_value=0,
        max_value=255,
        visible_if={"gpio_i2c_enabled": [True]},
    )
    """The I2C register read to know whether the output switch is high, or None if it is on a GPIO pin."""

    active_low: bool = config_field(
        label=N_("Active Level"),
        help_text=N_(
            "Choose Low if your device turns on when the pin is connected to ground, as most relay modules do.",
        ),
        choices=[LabeledValue(value=False, label=N_("High")), LabeledValue(value=True, label=N_("Low"))],
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
        gpio_pin = self._config.gpio_pin
        if self._config.gpio_i2c_enabled or gpio_pin is None:
            return frozenset()
        return frozenset({gpio_pin})

    def setup(self) -> None:
        """Set up the pin of the switch.

        A switch driven through I2C has no pin, so nothing is set up.

        Raises:
            ValueError: If the pin is not set.
            Exception: If the pin can't be set up.

        """
        config = self._config

        if config.gpio_i2c_enabled:
            return

        gpio_pin = config.gpio_pin
        if gpio_pin is None:
            msg = "The GPIO pin of the switch is not set"
            raise ValueError(msg)

        initial_value = self._gpio.HIGH if config.active_low else self._gpio.LOW
        self._logger.debug("Setting GPIO pin %s as OUTPUT with initial value: %s", gpio_pin, initial_value)
        self._gpio.setup(gpio_pin, self._gpio.OUT, initial=initial_value)

    def is_on(self) -> bool:
        """Read whether the switch is on.

        Returns:
            bool: Whether the switch is on.

        Raises:
            ValueError: If the pin or the I2C fields of the switch are not set.
            Exception: If the switch can't be read.

        """
        config = self._config

        if config.gpio_i2c_enabled:
            bus_number, address = config.gpio_i2c_bus, config.gpio_i2c_address
            register, data_on = config.gpio_i2c_register_status, config.gpio_i2c_data_on
            if bus_number is None or address is None or register is None or data_on is None:
                msg = "The I2C fields of the switch are not set"
                raise ValueError(msg)

            with self._i2c.SMBus(bus_number) as bus:
                data = bus.read_i2c_block_data(address, register, 1)
            self._logger.debug("Read %s from register %s", data, register)
            high = data[0] == data_on
        else:
            gpio_pin = config.gpio_pin
            if gpio_pin is None:
                msg = "The GPIO pin of the switch is not set"
                raise ValueError(msg)

            high = bool(self._gpio.input(gpio_pin))

        return high != config.active_low

    def set(self, *, on: bool) -> None:
        """Turn the switch on or off.

        Args:
            on (bool): Whether to turn the switch on or off.

        Raises:
            ValueError: If the pin or the I2C fields of the switch are not set.
            Exception: If the switch can't be written.

        """
        config = self._config
        high = on != config.active_low

        if config.gpio_i2c_enabled:
            bus_number, address, register = config.gpio_i2c_bus, config.gpio_i2c_address, config.gpio_i2c_register
            data = config.gpio_i2c_data_on if high else config.gpio_i2c_data_off
            if bus_number is None or address is None or register is None or data is None:
                msg = "The I2C fields of the switch are not set"
                raise ValueError(msg)

            with self._i2c.SMBus(bus_number) as bus:
                bus.write_i2c_block_data(address, register, [data])
            self._logger.debug("Writing on GPIO (i2c): %s/%s value %s", address, register, high)
        else:
            gpio_pin = config.gpio_pin
            if gpio_pin is None:
                msg = "The GPIO pin of the switch is not set"
                raise ValueError(msg)

            self._gpio.output(gpio_pin, high)
            self._logger.debug("Writing on GPIO: %s value %s", gpio_pin, high)
