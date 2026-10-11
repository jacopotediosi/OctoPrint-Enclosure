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


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Limit a value to the range between minimum and maximum."""
    return max(min(maximum, value), minimum)
