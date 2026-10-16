"""Open-Smart RGB LED Strip driver for the Raspberry Pi.

The protocol comes from Open-Smart-RGB-LED-Strip-Driver-for-Raspberry-Pi by Tim Richardson
(https://github.com/GeekyTim/Open-Smart-RGB-LED-Strip-Driver-for-Raspberry-Pi),
released under the GNU General Public License v3.0,
in turn based on Catalex-Led-Strip-Driver-Raspberry-Pi by Philip Leder
(https://github.com/schlank/Catalex-Led-Strip-Driver-Raspberry-Pi).
"""

from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Output

FRAME_BITS = 32


@dataclass(frozen=True)
class LedstripConfig(BaseConfig):
    """The configuration of an Open-Smart RGB LED strip."""

    ledstrip_gpio_clk: int
    """The GPIO pin of the clock signal (CLK)."""

    ledstrip_gpio_dat: int
    """The GPIO pin of the data signal (DAT)."""


class LedstripOutput(Output[LedstripConfig]):
    """An Open-Smart RGB LED strip output."""

    config_class = LedstripConfig

    def set_color(self, red: int, green: int, blue: int) -> None:
        """Set the color of the strip.

        Args:
            red (int): The red component, from 0 to 255.
            green (int): The green component, from 0 to 255.
            blue (int): The blue component, from 0 to 255.

        Raises:
            Exception: If the color can't be set.

        """
        self._gpio.setwarnings(False)
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setup(self.config.ledstrip_gpio_clk, self._gpio.OUT)
        self._gpio.setup(self.config.ledstrip_gpio_dat, self._gpio.OUT)

        # Two flag bits at 1, the check bits of the color components, then blue, green and red
        frame = 0b11 << 30
        frame |= self._get_check_bits(blue)
        frame |= self._get_check_bits(green)
        frame |= self._get_check_bits(red)
        frame |= blue << 16
        frame |= green << 8
        frame |= red

        # The frame goes between two frames of zeros
        self._send_bits(0, FRAME_BITS)
        self._send_bits(frame, FRAME_BITS)
        self._send_bits(0, FRAME_BITS)

    @staticmethod
    def _get_check_bits(component: int) -> int:
        # The complement of bits 7 and 6 of the component
        check_bits = 0
        if component & 0x80 == 0:
            check_bits |= 0b10
        if component & 0x40 == 0:
            check_bits |= 0b01
        return check_bits

    def _send_bits(self, value: int, count: int) -> None:
        # The most significant bit first, with a clock pulse after each one
        for bit in reversed(range(count)):
            self._gpio.output(self.config.ledstrip_gpio_dat, bool((value >> bit) & 1))
            self._gpio.output(self.config.ledstrip_gpio_clk, False)
            self._gpio.output(self.config.ledstrip_gpio_clk, True)

    @override
    def run_enc_command(self, command: str) -> None:
        return None
