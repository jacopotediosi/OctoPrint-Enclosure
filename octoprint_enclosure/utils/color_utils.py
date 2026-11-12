from __future__ import annotations

import re
from typing import NamedTuple

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


def format_hex_color(color: Rgb) -> str:
    """Write a color in the "#rrggbb" format.

    Args:
        color (Rgb): The red, green and blue components.

    Returns:
        str: The color, as "#" and six lowercase hexadecimal digits.

    Examples:
        >>> format_hex_color(Rgb(10, 20, 30))
        '#0a141e'

    """
    return f"#{color.red:02x}{color.green:02x}{color.blue:02x}"
