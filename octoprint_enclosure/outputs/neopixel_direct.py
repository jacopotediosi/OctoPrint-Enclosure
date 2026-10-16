from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from subprocess import Popen

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Output

WORKER_PATH = Path(__file__).with_name("neopixel_direct_worker.py")
SPI_PIN = 10


@dataclass(frozen=True)
class NeopixelDirectConfig(BaseConfig):
    """The configuration of NeoPixels connected directly to the Raspberry Pi."""

    gpio_pin: int
    """The GPIO pin the NeoPixels are connected to."""

    neopixel_count: int
    """The number of NeoPixels."""

    neopixel_brightness: int
    """The brightness of the NeoPixels, from 0 to 255."""

    neopixel_dma: int = 10
    """The DMA channel used to drive the NeoPixels."""


class NeopixelDirectOutput(Output[NeopixelDirectConfig]):
    """NeoPixels connected directly to a GPIO pin of the Raspberry Pi."""

    config_class = NeopixelDirectConfig

    def set_color(self, red: int, green: int, blue: int) -> None:
        """Set the color of all the NeoPixels.

        Args:
            red (int): The red component, from 0 to 255.
            green (int): The green component, from 0 to 255.
            blue (int): The blue component, from 0 to 255.

        Raises:
            Exception: If setting color fails.

        """
        config = self.config

        command = [
            sys.executable,
            str(WORKER_PATH),
            str(config.gpio_pin),
            str(config.neopixel_count),
            str(config.neopixel_brightness),
            str(red),
            str(green),
            str(blue),
            str(config.neopixel_dma),
        ]

        # rpi_ws281x requires root, except on the pin it drives through SPI
        if os.geteuid() != 0 and config.gpio_pin != SPI_PIN:
            command = ["sudo", "-n", *command]

        self._logger.debug("Running the NeoPixel worker: %s", command)
        Popen(command)

    @override
    def run_enc_command(self, command: str) -> None:
        return None
