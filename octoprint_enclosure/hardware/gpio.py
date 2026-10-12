"""RPi.GPIO, imported when first used.

Every attribute is forwarded to RPi.GPIO, which is imported on the first access. Outside a Raspberry Pi its import
raises a RuntimeError: deferring it lets the plugin load, and the error comes from the first GPIO call instead.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Shows the signatures of RPi.GPIO to editors and type checkers
    from RPi.GPIO import *  # noqa: F403 # pyright: ignore[reportWildcardImportFromLibrary]


def get_import_error() -> Exception | None:
    """Try to import RPi.GPIO and return the import error.

    Returns:
        Exception | None: The error raised by the import, or None if RPi.GPIO imports.

    """
    try:
        importlib.import_module("RPi.GPIO")
    except (ImportError, RuntimeError) as error:
        return error
    else:
        return None


def __getattr__(name: str) -> object:
    """Forward the attribute to RPi.GPIO, importing it if needed.

    Args:
        name (str): The name of the attribute.

    Returns:
        object: The requested attribute of RPi.GPIO.

    Raises:
        AttributeError: If the requested attribute is a dunder. Python probes dunders expecting at most an
            AttributeError (e.g. __path__ in "from <module> import <name>"), while importing RPi.GPIO outside a
            Raspberry Pi raises a RuntimeError.

    """
    if name.startswith("__") and name.endswith("__"):
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)

    return getattr(importlib.import_module("RPi.GPIO"), name)
