from __future__ import annotations


def N_(text: str) -> str:  # noqa: N802 - N_ is one of the names pybabel extracts by default
    """Mark a text for translation, leaving it unchanged.

    The text is translated where it is shown, e.g. by `_()` in a template.

    Args:
        text (str): The text, in English.

    Returns:
        str: The same text.

    Examples:
        >>> N_("Sensor Type")
        'Sensor Type'

    """
    return text
