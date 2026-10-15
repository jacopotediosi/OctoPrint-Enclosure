from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from typing import TYPE_CHECKING, Any, Callable, NewType, get_type_hints

from octoprint_enclosure.utils import parse_bool, parse_float, parse_hex

if TYPE_CHECKING:
    from typing_extensions import Self

HexInt = NewType("HexInt", int)
"""An integer saved in hexadecimal, such as an I2C address: "76" and "0x76" are both read as 118."""

_PARSERS: dict[Any, Callable[[Any], Any]] = {
    str: str,
    int: int,
    float: parse_float,
    bool: parse_bool,
    HexInt: parse_hex,
}
"""How to read a saved value, for each type a field of a configuration can have."""


@dataclass(frozen=True)
class BaseConfig:
    """A configuration read from settings: each field reads the key with its name."""

    @classmethod
    def from_settings(cls, settings: dict) -> Self:
        """Read the configuration from settings.

        A key that is missing or empty gives the default of its field.

        Args:
            settings (dict): The settings to read.

        Returns:
            Self: The configuration.

        Raises:
            TypeError: If a field has a type that can't be read from settings.
            ValueError: If a key is missing or empty and its field has no default, or its value is not valid for its
                field or for the configuration.

        Examples:
            >>> @dataclass(frozen=True)
            ... class I2cConfig(BaseConfig):
            ...     temp_sensor_address: HexInt
            ...     temp_sensor_i2cbus: int = 1
            >>> I2cConfig.from_settings({"label": "Enclosure", "temp_sensor_address": "38", "temp_sensor_i2cbus": "3"})
            I2cConfig(temp_sensor_address=56, temp_sensor_i2cbus=3)
            >>> I2cConfig.from_settings({"label": "Enclosure", "temp_sensor_address": "38", "temp_sensor_i2cbus": ""})
            I2cConfig(temp_sensor_address=56, temp_sensor_i2cbus=1)

        """
        type_hints = get_type_hints(cls)
        values = {}

        for field in fields(cls):
            parse = _PARSERS.get(type_hints[field.name])
            if parse is None:
                msg = f"{field.name} has a type that can't be read from settings: {type_hints[field.name]}"
                raise TypeError(msg)

            value = settings.get(field.name, "")
            if value == "":
                if field.default is MISSING:
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
