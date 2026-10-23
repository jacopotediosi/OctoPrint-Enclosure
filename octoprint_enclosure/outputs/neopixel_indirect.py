from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig, HexInt
from octoprint_enclosure.utils import get_gcode_param, to_int

from .color import ColorOutput

BUS = 1


@dataclass(frozen=True)
class NeopixelIndirectConfig(BaseConfig):
    """The configuration of NeoPixels driven by a microcontroller on the I2C bus."""

    gpio_pin: int
    """The pin of the microcontroller the NeoPixels are connected to."""

    neopixel_count: int
    """The number of NeoPixels."""

    neopixel_brightness: int
    """The brightness of the NeoPixels, from 0 to 255."""

    microcontroller_address: HexInt
    """The I2C address of the microcontroller."""


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
        index_id = to_int(get_gcode_param(command, "O"))
        red, green, blue = (int(get_gcode_param(command, letter)) for letter in "RGB")

        self.set_color(red, green, blue)

        return f"Setting NEOPIXEL output {index_id} to red: {red} green: {green} blue: {blue}"
