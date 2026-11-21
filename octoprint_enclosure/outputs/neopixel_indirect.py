from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.settings import HexInt, setting
from octoprint_enclosure.utils import Rgb, get_gcode_param

from .color import ColorOutput, ColorSetpoint
from .config import OutputConfig

BUS = 1


@dataclass(frozen=True)
class NeopixelIndirectConfig(OutputConfig):
    """The configuration of NeoPixels driven by a microcontroller on the I2C bus."""

    microcontroller_address: HexInt = setting(
        label="Microcontroller Address",
        help_text=(
            "Address of the microcontroller, in hexadecimal. Find it by running <code>i2cdetect -y 1</code> (from the "
            "<code>i2c-tools</code> package) on your Raspberry Pi."
        ),
    )
    """The I2C address of the microcontroller."""

    gpio_pin: int = setting(
        label="Microcontroller Pin",
        help_text=(
            '<span class="label label-important">Attention</span> NeoPixels need a microcontroller (e.g., an Arduino) '
            "connected to the I2C bus, which needs to be enabled: run <code>sudo raspi-config</code> and enable I2C "
            "in the interface options. This is the pin of the microcontroller the NeoPixels are connected to."
        ),
        min_value=0,
        max_value=255,
    )
    """The pin of the microcontroller the NeoPixels are connected to."""

    neopixel_count: int = setting(
        label="Number of LEDs",
        help_text="Number of LEDs on the strip.",
        min_value=1,
        max_value=255,
    )
    """The number of NeoPixels."""

    neopixel_brightness: int = setting(
        default=255,
        label="Brightness",
        help_text="Value between 0 and 255.",
        min_value=0,
        max_value=255,
    )
    """The brightness of the NeoPixels, from 0 to 255."""


class NeopixelIndirectOutput(ColorOutput[NeopixelIndirectConfig]):
    """NeoPixels driven by a microcontroller on the I2C bus."""

    config_class = NeopixelIndirectConfig

    @override
    def _write_color(self, red: int, green: int, blue: int) -> None:
        config = self.config

        # The microcontroller reads pin, count, brightness, red, green and blue from register 0
        data = [config.gpio_pin, config.neopixel_count, config.neopixel_brightness, red, green, blue]
        self._logger.debug("Writing %s to I2C address %s", data, config.microcontroller_address)
        with self._i2c.SMBus(BUS) as bus:
            bus.write_i2c_block_data(config.microcontroller_address, 0, data)

    @override
    def run_enc_command(self, command: str) -> str:
        red, green, blue = (int(get_gcode_param(command, letter)) for letter in "RGB")

        self.turn_on(ColorSetpoint(Rgb(red, green, blue)))

        return f"Setting NEOPIXEL output {self.config.index_id} to red: {red} green: {green} blue: {blue}"
