from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, FrozenSet, NewType, Optional, get_type_hints

from octoprint_enclosure.utils import Rgb, parse_bool, parse_float, parse_hex, parse_hex_color

if TYPE_CHECKING:
    from typing_extensions import Self

HexInt = NewType("HexInt", int)
"""An integer saved in hexadecimal, such as an I2C address: "76" and "0x76" are both read as 118."""


class _Required:
    """The marker of a field whose key must be set."""


REQUIRED: Any = _Required()
"""The default of a field whose key must be set."""


def _parse_str_set(value: Any) -> frozenset[str]:  # noqa: ANN401 - value is purposely untyped
    """Read a saved list of strings, with at least one, as a set."""
    if not isinstance(value, (list, tuple, set, frozenset)) or not all(isinstance(item, str) for item in value):
        msg = f"not a list of strings: {value!r}"
        raise ValueError(msg)
    if not value:
        msg = "the list is empty"
        raise ValueError(msg)
    return frozenset(value)


_PARSERS: dict[Any, Callable[[Any], Any]] = {
    str: str,
    int: int,
    float: parse_float,
    Optional[float]: parse_float,
    bool: parse_bool,
    HexInt: parse_hex,
    Rgb: parse_hex_color,
    FrozenSet[str]: _parse_str_set,
}
"""How to read a saved value, for each type a field of a configuration can have."""


@dataclass(frozen=True)
class BaseConfig:
    """A configuration read from settings: each field reads the key with its name."""

    @classmethod
    def from_settings(cls, settings: dict) -> Self:
        """Read the configuration from settings.

        A key that is missing, empty or null gives the default of its field. A field with no default, or with
        REQUIRED as default, needs its key.

        Args:
            settings (dict): The settings to read.

        Returns:
            Self: The configuration.

        Raises:
            TypeError: If a field has a type that can't be read from settings.
            ValueError: If a key is missing, empty or null and its field needs it, or its value is not valid for its
                field or for the configuration.

        Examples:
            >>> @dataclass(frozen=True)
            ... class I2cConfig(BaseConfig):
            ...     temp_sensor_address: HexInt = REQUIRED
            ...     temp_sensor_i2cbus: int = 1
            >>> I2cConfig.from_settings({"label": "Enclosure", "temp_sensor_address": "38", "temp_sensor_i2cbus": "3"})
            I2cConfig(temp_sensor_address=56, temp_sensor_i2cbus=3)
            >>> I2cConfig.from_settings({"label": "Enclosure", "temp_sensor_address": "38", "temp_sensor_i2cbus": ""})
            I2cConfig(temp_sensor_address=56, temp_sensor_i2cbus=1)

        """
        type_hints = get_type_hints(cls)
        values = {}

        for field in fields(cls):
            type_hint = type_hints[field.name]
            parse = _PARSERS.get(type_hint)
            if parse is None and isinstance(type_hint, type) and issubclass(type_hint, Enum):
                parse = type_hint
            if parse is None:
                msg = f"{field.name} has a type that can't be read from settings: {type_hint}"
                raise TypeError(msg)

            value = settings.get(field.name, "")
            if value == "" or value is None:
                if field.default is MISSING or field.default is REQUIRED:
                    msg = f"{field.name} is not set"
                    raise ValueError(msg)

                # The dataclass fills in the default
                continue

            try:
                values[field.name] = parse(value)
            except (TypeError, ValueError, OverflowError) as error:
                msg = f"{field.name}: {error}"
                raise ValueError(msg) from error

        return cls(**values)
