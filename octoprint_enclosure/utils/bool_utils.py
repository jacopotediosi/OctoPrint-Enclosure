from __future__ import annotations

from typing import Any


def parse_bool(value: Any) -> bool:  # noqa: ANN401 - value is purposely untyped
    """Convert a boolean, or the string "true" or "false" in any case, to bool.

    Args:
        value (Any): The value.

    Returns:
        bool: The converted value.

    Raises:
        ValueError: If the value is neither a boolean nor the string "true" or "false".

    Examples:
        >>> parse_bool("False")
        False
        >>> parse_bool(True)
        True

    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    msg = f"not a boolean: {value!r}"
    raise ValueError(msg)
