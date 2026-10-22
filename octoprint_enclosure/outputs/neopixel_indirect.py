from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig, HexInt

from .base import Output

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


class NeopixelIndirectOutput(Output[NeopixelIndirectConfig]):
    """NeoPixels driven by a microcontroller on the I2C bus."""

    config_class = NeopixelIndirectConfig

    def set_color(self, red: int, green: int, blue: int) -> None:
        """Set the color of all the NeoPixels.

        Args:
            red (int): The red component, from 0 to 255.
            green (int): The green component, from 0 to 255.
            blue (int): The blue component, from 0 to 255.

        Raises:
            Exception: If the color can't be sent to the microcontroller.

        """
        config = self.config

        # The microcontroller reads pin, count, brightness, red, green and blue from register 0
        data = [config.gpio_pin, config.neopixel_count, config.neopixel_brightness, red, green, blue]
        self._logger.debug("Writing %s to I2C address %s", data, config.microcontroller_address)
        with self._i2c.SMBus(BUS) as bus:
            bus.write_i2c_block_data(config.microcontroller_address, 0, data)

    @override
    def run_enc_command(self, command: str) -> None:
        return None
