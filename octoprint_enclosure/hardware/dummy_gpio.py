"""Dummy GPIO pins with the API of RPi.GPIO, used in development mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import Final, Literal, TypeAlias

    _PinNumbering: TypeAlias = Literal[10, 11]  # BOARD or BCM
    _Direction: TypeAlias = Literal[0, 1]  # OUT or IN
    _Level: TypeAlias = Literal[0, 1] | bool  # LOW or HIGH, or False or True

HIGH: Final = 1
LOW: Final = 0

OUT: Final = 0
IN: Final = 1

BOARD: Final = 10
BCM: Final = 11

PUD_OFF: Final = 20
PUD_DOWN: Final = 21
PUD_UP: Final = 22

RISING: Final = 31
FALLING: Final = 32
BOTH: Final = 33


class _PinState:
    """The state of the dummy pins."""

    mode: _PinNumbering | None
    levels: dict[int, int]
    event_callbacks: dict[int, Callable[[int], object] | None]

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.mode = None
        self.levels = {}
        self.event_callbacks = {}


class PWM:
    """Dummy software PWM on a pin."""

    def __init__(self, channel: int, frequency: float) -> None:
        """Set up the PWM,.

        Args:
            channel (int): The pin the PWM runs on.
            frequency (float): The frequency of the PWM, in Hz.

        """
        self.channel = channel
        self.frequency = frequency
        self.duty_cycle = 0.0
        self.running = False

    def start(self, dutycycle: float) -> None:
        """Start the PWM with a duty cycle, from 0 to 100."""
        self.duty_cycle = dutycycle
        self.running = True

    def stop(self) -> None:
        """Stop the PWM."""
        self.running = False


_pin_state = _PinState()


def _as_list(channel: int | list[int] | tuple[int, ...]) -> list[int]:
    return list(channel) if isinstance(channel, (list, tuple)) else [channel]


def setwarnings(gpio_warnings: bool) -> None:  # noqa: FBT001 - same signature as RPi.GPIO.setwarnings
    pass


def setmode(mode: _PinNumbering) -> None:
    _pin_state.mode = mode


def getmode() -> _PinNumbering | None:
    return _pin_state.mode


def setup(
    channel: int | list[int] | tuple[int, ...],
    direction: _Direction,
    pull_up_down: int = PUD_OFF,
    initial: int = -1,
) -> None:
    for pin in _as_list(channel):
        if direction == OUT:
            _pin_state.levels[pin] = _pin_state.levels.get(pin, LOW) if initial == -1 else (HIGH if initial else LOW)
        else:
            _pin_state.levels[pin] = HIGH if pull_up_down == PUD_UP else LOW


def output(
    channel: int | list[int] | tuple[int, ...],
    value: _Level | list[_Level] | tuple[_Level, ...],
) -> None:
    pins = _as_list(channel)
    values = list(value) if isinstance(value, (list, tuple)) else [value] * len(pins)
    for pin, pin_value in zip(pins, values):
        _pin_state.levels[pin] = HIGH if pin_value else LOW


def input(channel: int) -> int:  # noqa: A001 - same name as RPi.GPIO.input
    return _pin_state.levels.get(channel, LOW)


def cleanup(channel: int | list[int] | tuple[int, ...] | None = None) -> None:
    if channel is None:
        _pin_state.reset()
        return

    for pin in _as_list(channel):
        _pin_state.levels.pop(pin, None)
        _pin_state.event_callbacks.pop(pin, None)


def add_event_detect(
    channel: int,
    edge: int,  # noqa: ARG001 - same signature as RPi.GPIO.add_event_detect
    callback: Callable[[int], object] | None = None,
    bouncetime: int | None = None,  # noqa: ARG001 - same signature as RPi.GPIO.add_event_detect
) -> None:
    _pin_state.event_callbacks[channel] = callback


def remove_event_detect(channel: int) -> None:
    _pin_state.event_callbacks.pop(channel, None)
