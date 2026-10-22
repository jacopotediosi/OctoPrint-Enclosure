"""A dummy I2C bus with the API of smbus2, used in development mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .i2c_backend import I2cBus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from typing_extensions import Self

_registers: dict[tuple[int, int, int], int] = {}
"""The value of each register written so far, by bus, device address and register."""


class SMBus(I2cBus):
    """A dummy I2C bus."""

    bus: int
    """The number of the bus."""

    def __init__(self, bus: int) -> None:
        """Open the bus.

        Args:
            bus (int): The number of the bus.

        """
        self.bus = bus

    def __enter__(self) -> Self:
        """Enter the with statement, returning the bus."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the bus at the end of the with statement."""

    def write_i2c_block_data(self, i2c_addr: int, register: int, data: Sequence[int]) -> None:
        for offset, value in enumerate(data):
            _registers[(self.bus, i2c_addr, register + offset)] = value

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int) -> list[int]:
        return [_registers.get((self.bus, i2c_addr, register + offset), 0) for offset in range(length)]


def get_registers() -> dict[tuple[int, int, int], int]:
    """Get the registers written so far.

    Returns:
        dict[tuple[int, int, int], int]: The value of each register, by bus, device address and register.

    """
    return dict(_registers)
