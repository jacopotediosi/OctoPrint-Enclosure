"""The API of the I2C backend.

The I2C backend is smbus2, or its dummy in development mode, and the components receive one or the other. This
protocol is the type they receive it as: the calls the plugin makes, with their signatures, so that type checkers
check the calls and verify that the dummy offers the same ones as smbus2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

    from typing_extensions import Self


class I2cBus(Protocol):
    """An open I2C bus, with the API of smbus2.SMBus."""

    def __enter__(self) -> Self:
        """Enter the with statement, returning the bus."""
        ...

    def __exit__(
        self,
        __exc_type: type[BaseException] | None,
        __exc_value: BaseException | None,
        __traceback: TracebackType | None,
    ) -> None:
        """Close the bus at the end of the with statement."""
        ...

    def write_i2c_block_data(self, i2c_addr: int, register: int, data: Sequence[int]) -> None:
        """Write some bytes to a device, starting from a register."""
        ...

    def read_i2c_block_data(self, i2c_addr: int, register: int, length: int) -> list[int]:
        """Read some bytes from a device, starting from a register."""
        ...


class I2cBackend(Protocol):
    """The I2C backend, with the API of smbus2."""

    def SMBus(self, bus: int) -> I2cBus:  # noqa: N802 - same name as smbus2.SMBus
        """Open an I2C bus by its number."""
        ...
