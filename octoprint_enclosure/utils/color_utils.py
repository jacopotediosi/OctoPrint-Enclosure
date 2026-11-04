from __future__ import annotations

import re
from typing import NamedTuple

_COMPONENT = r"(?:25[0-5]|2[0-4]\d|1?\d{1,2})"
_RGB_PATTERN = re.compile(rf"rgb\(\s*{_COMPONENT}\s*,\s*{_COMPONENT}\s*,\s*{_COMPONENT}\s*\)")
_HEX_COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


class Rgb(NamedTuple):
    """A color, as its red, green and blue components from 0 to 255."""

    red: int
    green: int
    blue: int


def parse_hex_color(value: str) -> Rgb:
    """Read a color in the "#rrggbb" format.

    Args:
        value (str): The color, as "#" and six hexadecimal digits.

    Returns:
        Rgb: The red, green and blue components.

    Raises:
        ValueError: If the text is not in the "#rrggbb" format.

    Examples:
        >>> parse_hex_color("#0a141e")
        Rgb(red=10, green=20, blue=30)
        >>> parse_hex_color("rgb(10,20,30)")
        Traceback (most recent call last):
        ...
        ValueError: 'rgb(10,20,30)' is not a color in the #rrggbb format

    """
    if _HEX_COLOR_PATTERN.fullmatch(value) is None:
        msg = f"{value!r} is not a color in the #rrggbb format"
        raise ValueError(msg)
    return Rgb(*(int(value[start : start + 2], 16) for start in (1, 3, 5)))


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
