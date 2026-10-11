from __future__ import annotations


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
