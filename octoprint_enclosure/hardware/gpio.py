"""RPi.GPIO, imported when first used.

Every attribute is forwarded to RPi.GPIO, which is imported on the first access. Outside a Raspberry Pi its import
raises a RuntimeError: deferring it lets the plugin load, and the error comes from the first GPIO call instead.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    # Shows the signatures of RPi.GPIO to editors and type checkers
    from RPi.GPIO import *  # noqa: F403 # pyright: ignore[reportWildcardImportFromLibrary]

    from .gpio_backend import Channel, Direction, GpioBackend


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


def _rpi_gpio_in_bcm() -> GpioBackend:
    rpi_gpio = cast("GpioBackend", importlib.import_module("RPi.GPIO"))
    if rpi_gpio.getmode() is None:
        rpi_gpio.setmode(rpi_gpio.BCM)
    elif rpi_gpio.getmode() != rpi_gpio.BCM:
        msg = "GPIO numbering is BOARD, set by another plugin: this plugin needs BCM"
        raise RuntimeError(msg)
    rpi_gpio.setwarnings(False)
    return rpi_gpio


def _setup(channel: Channel, direction: Direction, *args: int, **kwargs: int) -> None:
    """Set up a channel with RPi.GPIO, in BCM numbering.

    Args:
        channel (Channel): The BCM number of the pin, or a list of them.
        direction (Direction): IN or OUT.
        *args (int): The other arguments of the setup of RPi.GPIO.
        **kwargs (int): The other arguments of the setup of RPi.GPIO.

    Raises:
        RuntimeError: If the pin numbering is BOARD, set by another plugin, or if the channel can't be set up.

    """
    _rpi_gpio_in_bcm().setup(channel, direction, *args, **kwargs)


def _cleanup(channel: Channel) -> None:
    """Clean up a channel with RPi.GPIO, in BCM numbering.

    Args:
        channel (Channel): The BCM number of the pin, or a list of them.

    Raises:
        RuntimeError: If the pin numbering is BOARD, set by another plugin, or if the channel can't be cleaned up.

    """
    _rpi_gpio_in_bcm().cleanup(channel)


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

    if name == "setup":
        return _setup
    if name == "cleanup":
        return _cleanup

    return getattr(importlib.import_module("RPi.GPIO"), name)
