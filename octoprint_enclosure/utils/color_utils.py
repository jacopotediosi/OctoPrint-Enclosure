from __future__ import annotations

import re

_COMPONENT = r"(?:25[0-5]|2[0-4]\d|1?\d{1,2})"
_RGB_PATTERN = re.compile(rf"rgb\(\s*{_COMPONENT}\s*,\s*{_COMPONENT}\s*,\s*{_COMPONENT}\s*\)")


def is_rgb(value: str) -> bool:
    """Check if a string is a color in the "rgb(r,g,b)" format.

    Args:
        value (str): The string to check.

    Returns:
        bool: True if the string is in the "rgb(r,g,b)" format, with components from 0 to 255 and spaces allowed
            around them.

    Examples:
        >>> is_rgb("rgb(255, 0, 0)")
        True
        >>> is_rgb("rgb(256,0,0)")
        False
        >>> is_rgb("255,0,0")
        False

    """
    return _RGB_PATTERN.fullmatch(value) is not None


def parse_rgb(rgb_string: str) -> tuple[str, str, str] | tuple[int, int, int]:
    """Split an "rgb(r,g,b)" string into its components.

    Args:
        rgb_string (str): The color, in the "rgb(r,g,b)" format.

    Returns:
        tuple: The red, green and blue components, or (0, 0, 0) if the string is empty.

    Raises:
        ValueError: If the string is not in the "rgb(r,g,b)" format.

    Examples:
        >>> parse_rgb("rgb(255,0,0)")
        ('255', '0', '0')
        >>> parse_rgb("")
        (0, 0, 0)

    """
    if not rgb_string:
        return 0, 0, 0

    red, green, rest = rgb_string.replace("rgb(", "").split(",", 2)
    blue = rest[: rest.index(")")]
    return red, green, blue
