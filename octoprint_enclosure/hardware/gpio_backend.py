"""The API of the GPIO backend.

The GPIO backend is RPi.GPIO, or its dummy in development mode, and the components receive one or the other. This
protocol is the type they receive it as: the calls the plugin makes, with their signatures, so that type checkers
check the calls and verify that the dummy offers the same ones as RPi.GPIO.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import Literal, TypeAlias

    Channel: TypeAlias = int | list[int] | tuple[int, ...]
    """A pin, or some pins."""

    PinNumbering: TypeAlias = Literal[10, 11]
    """The pin numbering, BOARD or BCM."""

    Direction: TypeAlias = Literal[0, 1]
    """The direction of a pin, OUT or IN."""

    Level: TypeAlias = Literal[0, 1] | bool
    """The level of a pin, LOW or HIGH, or False or True."""


class GpioPwm(Protocol):
    """A software PWM on a GPIO pin, with the API of RPi.GPIO.PWM."""

    def start(self, __dutycycle: float) -> None:
        """Start the PWM with a duty cycle, from 0 to 100."""
        ...

    def ChangeDutyCycle(self, __dutycycle: float) -> None:  # noqa: N802 - same name as RPi.GPIO.PWM.ChangeDutyCycle
        """Change the duty cycle, from 0 to 100."""
        ...

    def stop(self) -> None:
        """Stop the PWM."""
        ...


class GpioBackend(Protocol):
    """The GPIO backend, with the API of RPi.GPIO."""

    HIGH: Literal[1]
    LOW: Literal[0]

    OUT: Literal[0]
    IN: Literal[1]

    BOARD: Literal[10]
    BCM: Literal[11]

    PUD_OFF: Literal[20]
    PUD_DOWN: Literal[21]
    PUD_UP: Literal[22]

    RISING: Literal[31]
    FALLING: Literal[32]
    BOTH: Literal[33]

    def setwarnings(self, __gpio_warnings: bool) -> None:  # noqa: FBT001 - same signature as RPi.GPIO.setwarnings
        """Enable or disable the warnings."""
        ...

    def setmode(self, __mode: PinNumbering) -> None:
        """Set the pin numbering, BOARD or BCM."""
        ...

    def getmode(self) -> PinNumbering | None:
        """Get the pin numbering, BOARD or BCM, or None if it isn't set."""
        ...

    def setup(self, channel: Channel, direction: Direction, pull_up_down: int = ..., initial: int = ...) -> None:
        """Set up a pin, or some pins, as input or output.

        An input can have a pull resistor, and an output an initial level.
        """
        ...

    def output(self, __channel: Channel, __value: Level | list[Level] | tuple[Level, ...]) -> None:
        """Set the level of an output pin, or of some pins."""
        ...

    def input(self, __channel: int) -> int:
        """Read the level of a pin, 1 if high or 0 if low."""
        ...

    def cleanup(self, channel: Channel = ...) -> None:
        """Reset a pin, or some pins, or every pin set up so far.

        A pin is reset to input, with no pull resistor and no edge detection.
        """
        ...

    def add_event_detect(
        self,
        channel: int,
        edge: int,
        callback: Callable[[int], object] | None = ...,
        bouncetime: int = ...,
    ) -> None:
        """Start detecting an edge on a pin, RISING, FALLING or BOTH.

        A function, if given, is called with the pin at every edge, except the ones within the bounce time in ms
        after the previous one.
        """
        ...

    def remove_event_detect(self, __channel: int) -> None:
        """Stop detecting the edges on a pin."""
        ...

    def PWM(self, __channel: int, __frequency: float) -> GpioPwm:  # noqa: N802 - same name as RPi.GPIO.PWM
        """Create a software PWM on a pin, at a frequency in Hz."""
        ...
