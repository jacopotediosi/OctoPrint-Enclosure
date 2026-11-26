from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from operator import attrgetter
from typing import Any, Callable, FrozenSet, NewType

from octoprint_enclosure.utils import (
    Rgb,
    format_hex,
    format_hex_color,
    parse_bool,
    parse_float,
    parse_hex,
    parse_hex_color,
)

NO_DEFAULT: Any = object()
"""The value that marks a field with no default."""


##########
### Custom types
##########


HexInt = NewType("HexInt", int)
"""An integer saved in hexadecimal, such as an I2C address: "76" and "0x76" are both read as 118."""

SensorInputId = NewType("SensorInputId", int)
"""The id of an input with a temperature sensor."""

GpioInputId = NewType("GpioInputId", int)
"""The id of a GPIO input."""

OutputId = NewType("OutputId", int)
"""The id of an output."""

ActionId = NewType("ActionId", int)
"""The id of an action."""


##########
### Supported types
##########


def _keep_as_it_is(value: object) -> object:
    """Write a value that is saved as it is."""
    return value


@dataclass(frozen=True)
class FieldType:
    """Describes a type a field of a configuration can have."""

    name: str
    """The name of the type."""

    from_saved: Callable[[Any], Any]
    """The function that reads a saved value of the type."""

    value_types: tuple[type, ...]
    """The Python types a value of the type can have."""

    to_saved: Callable[[Any], Any] = _keep_as_it_is
    """The function that writes a value of the type as it is saved."""


def _parse_str_set(value: object) -> frozenset[str]:
    """Convert a saved list of strings, with at least one, to a set."""
    if not isinstance(value, (list, tuple, set, frozenset)) or not all(isinstance(item, str) for item in value):
        msg = f"not a list of strings: {value!r}"
        raise ValueError(msg)
    if not value:
        msg = "the list is empty"
        raise ValueError(msg)
    return frozenset(value)


def _format_str_set(value: frozenset[str]) -> list[str]:
    """Convert a set of strings to the list that is saved, sorted."""
    return sorted(value)


FIELD_TYPES: dict[Any, FieldType] = {
    str: FieldType(name="str", from_saved=str, value_types=(str,)),
    int: FieldType(name="int", from_saved=int, value_types=(int,)),
    float: FieldType(name="float", from_saved=parse_float, value_types=(int, float)),
    bool: FieldType(name="bool", from_saved=parse_bool, value_types=(bool,)),
    HexInt: FieldType(name="HexInt", from_saved=parse_hex, value_types=(int,), to_saved=format_hex),
    Rgb: FieldType(name="Rgb", from_saved=parse_hex_color, value_types=(Rgb,), to_saved=format_hex_color),
    FrozenSet[str]: FieldType(
        name="FrozenSet[str]",
        from_saved=_parse_str_set,
        value_types=(frozenset,),
        to_saved=_format_str_set,
    ),
    SensorInputId: FieldType(name="SensorInputId", from_saved=int, value_types=(int,)),
    GpioInputId: FieldType(name="GpioInputId", from_saved=int, value_types=(int,)),
    OutputId: FieldType(name="OutputId", from_saved=int, value_types=(int,)),
    ActionId: FieldType(name="ActionId", from_saved=int, value_types=(int,)),
}
"""The types a field of a configuration can have, each also as Optional."""


def get_non_optional_type(type_hint: object) -> object:
    """Get a type hint without Optional.

    Args:
        type_hint (object): The type hint, e.g. `Optional[int]`, `int`, etc.

    Returns:
        object: The type inside Optional, e.g. `int` for `Optional[int]`. A type hint that is not Optional is
            returned as it is.

    Examples:
        >>> from typing import Optional
        >>> get_non_optional_type(Optional[int])
        <class 'int'>
        >>> get_non_optional_type(str)
        <class 'str'>

    """
    arguments = getattr(type_hint, "__args__", ())
    if type(None) not in arguments:
        return type_hint
    return next(argument for argument in arguments if argument is not type(None))


def can_be_empty(type_hint: object) -> bool:
    """Tell whether a field with a certain type hint can be left empty.

    Args:
        type_hint (object): The type hint, e.g. `Optional[int]`, `str`, etc.

    Returns:
        bool: Whether the type hint is a text or Optional.

    Examples:
        >>> from typing import Optional
        >>> can_be_empty(Optional[int])
        True
        >>> can_be_empty(str)
        True
        >>> can_be_empty(int)
        False

    """
    return type_hint is str or get_non_optional_type(type_hint) is not type_hint


def get_non_optional_field_type(type_hint: object) -> FieldType:
    """Describe the type of a field. Raise KeyError if it can't be read from settings."""
    type_hint = get_non_optional_type(type_hint)
    if isinstance(type_hint, type) and issubclass(type_hint, Enum):
        return FieldType(name="Enum", from_saved=type_hint, value_types=(type_hint,), to_saved=attrgetter("value"))
    return FIELD_TYPES[type_hint]


##########
### Widgets
##########


WIDGET_TYPES: dict[str, tuple[Any, ...]] = {
    "id": (int,),
    "octoprint_events": (FrozenSet[str],),
    "output_setpoint": (float, Rgb),
    "pwm_output": (OutputId,),
    "temperature": (float,),
    "temperature_interval": (float,),
    "textarea": (str,),
    "thermostat_sensor": (SensorInputId,),
}
"""The widgets a field can declare, each with the types of the fields it is for."""
