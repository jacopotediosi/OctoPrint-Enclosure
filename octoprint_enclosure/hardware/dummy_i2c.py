"""A dummy I2C bus with the API of smbus2, used in development mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from typing_extensions import Self

_registers: dict[tuple[int, int, int], int] = {}
"""The value of each register written so far, by bus, device address and register."""


class SMBus:
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
        """Open the bus in a with statement."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the bus at the end of the with statement."""

    def write_i2c_block_data(self, i2c_addr: int, register: int, data: Sequence[int]) -> None:
        """Write some bytes to a device, each one to the register after the previous one.

        Args:
            i2c_addr (int): The address of the device.
            register (int): The register of the first byte.
            data (Sequence[int]): The bytes to write.

        """
        for offset, value in enumerate(data):
            _registers[(self.bus, i2c_addr, register + offset)] = value

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int) -> list[int]:
        """Read some bytes from a device, each one from the register after the previous one.

        Args:
            i2c_addr (int): The address of the device.
            register (int): The register of the first byte.
            length (int): How many bytes to read.

        Returns:
            list[int]: The bytes read, 0 for a register never written.

        """
        return [_registers.get((self.bus, i2c_addr, register + offset), 0) for offset in range(length)]


def get_registers() -> dict[tuple[int, int, int], int]:
    """Get the registers written so far.

    Returns:
        dict[tuple[int, int, int], int]: The value of each register, by bus, device address and register.

    """
    return dict(_registers)
