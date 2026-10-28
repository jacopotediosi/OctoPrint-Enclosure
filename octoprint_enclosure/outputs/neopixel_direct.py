from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.utils import get_gcode_param, to_int

from .base import OutputError
from .color import ColorOutput

WORKER_PATH = Path(__file__).with_name("neopixel_direct_worker.py")
WORKER_TIMEOUT_SECONDS = 3
WORKER_TERMINATE_TIMEOUT_SECONDS = 2

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


class NeopixelDirectOutput(ColorOutput[NeopixelDirectConfig]):
    """NeoPixels connected directly to a GPIO pin of the Raspberry Pi."""

    config_class = NeopixelDirectConfig

    @property
    @override
    def gpio_pins(self) -> frozenset[int]:
        return frozenset({self.config.gpio_pin})

    @override
    def _write_color(self, red: int, green: int, blue: int) -> None:
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
        with subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        ) as process:
            try:
                _, stderr = process.communicate(timeout=WORKER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=WORKER_TERMINATE_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                msg = f"The NeoPixel worker didn't end within {WORKER_TIMEOUT_SECONDS} s"
                raise OutputError(msg) from None

        if process.returncode != 0:
            msg = f"The NeoPixel worker exited with code {process.returncode}: {stderr.strip()}"
            raise OutputError(msg)

    @override
    def run_enc_command(self, command: str) -> str:
        index_id = to_int(get_gcode_param(command, "O"))
        red, green, blue = (int(get_gcode_param(command, letter)) for letter in "RGB")

        self.set_color(red, green, blue)

        return f"Setting NEOPIXEL output {index_id} to red: {red} green: {green} blue: {blue}"
