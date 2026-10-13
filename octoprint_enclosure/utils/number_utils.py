from __future__ import annotations

from typing import Any


def to_float(value: Any) -> float:  # noqa: ANN401 - value is purposely untyped
    """Convert a value to float, or return 0 if it can't be converted."""
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def to_int(value: Any) -> int:  # noqa: ANN401 - value is purposely untyped
    """Convert a value to int, or return 0 if it can't be converted."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def parse_hex(value: Any) -> int:  # noqa: ANN401 - value is purposely untyped
    """Convert a hexadecimal value to int.

    Args:
        value (Any): The value, with or without the 0x prefix.

    Returns:
        int: The converted value.

    Raises:
        ValueError: If the value is not a hexadecimal number.

    Examples:
        >>> parse_hex("48")
        72
        >>> parse_hex("0x48")
        72

    """
    return int(str(value), 16)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limit a value to the range between minimum and maximum."""
    return max(min(maximum, value), minimum)
