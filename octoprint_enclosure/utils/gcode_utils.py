from __future__ import annotations


def get_gcode_param(command: str, letter: str) -> str | int:
    """Get the value of a parameter in a G-code line.

    Args:
        command (str): The G-code line.
        letter (str): The letter of the parameter.

    Returns:
        str | int: The value of the parameter, or -1 if the G-code line doesn't contain it.

    Examples:
        >>> get_gcode_param("M106 S255", "S")
        '255'
        >>> get_gcode_param("M106 S255", "P")
        -1

    """
    code = command.split(";", 1)[0]
    for token in code.split(" "):
        if letter.upper() in token.upper():
            return token.replace(letter, "")
    return -1
