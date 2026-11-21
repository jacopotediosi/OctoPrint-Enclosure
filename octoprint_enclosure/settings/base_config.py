from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from dataclasses import field as dataclass_field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ClassVar, FrozenSet, NewType, Optional, TypeVar, get_type_hints

from octoprint_enclosure.utils import (
    LabeledEnum,
    Rgb,
    format_hex_color,
    parse_bool,
    parse_float,
    parse_hex,
    parse_hex_color,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from typing_extensions import Self

    from octoprint_enclosure.utils import LabeledValue

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

_IdT = TypeVar("_IdT", bound=int)
_DefaultT = TypeVar("_DefaultT")


_NO_DEFAULT: Any = object()
"""The default of a field that has none."""


def setting(
    *,
    default: _DefaultT = _NO_DEFAULT,
    optional: bool = False,
    label: str = "",
    help_text: str = "",
    choices: Sequence[LabeledValue | LabeledEnum] | None = None,
    unit: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    visible_if: Mapping[str, Sequence[Any]] | None = None,
    widget: str = "",
    compare: bool = True,
) -> _DefaultT:
    """Declare a field of a configuration.

    Args:
        default (_DefaultT): The value of the field in a new item. Without one, the field starts empty.
        optional (bool): Whether the field can be left empty.
        label (str): The label of the field.
        help_text (str): The help text (can also contain HTML).
        choices (Sequence[LabeledValue | LabeledEnum] | None): The values the field can be set to, in order:
            some of its members, for a field that is a LabeledEnum, or each value with its label, for the other
            fields. None for every member of a LabeledEnum, and for a field that can have any value.
        unit (str): The unit of the value, e.g. "Hz", "s", etc.
        min_value (float | None): The lowest value a numeric field accepts, or None for no limit.
        max_value (float | None): The highest value a numeric field accepts, or None for no limit.
        visible_if (Mapping[str, Sequence[Any]] | None): When the field is used: for each of the other fields it
            names, the values that field can have. None if the field is always used.
        widget (str): The widget of the field, e.g. "temperature", "textarea", etc. Empty for the default one of the
            type of the field.
        compare (bool): Whether the field counts when two configurations are compared.

    Returns:
        _DefaultT: The field, to assign in the body of the configuration dataclass.

    Examples:
        >>> @dataclass(frozen=True)
        ... class PwmConfig(BaseConfig):
        ...     pwm_frequency: int = setting(label="PWM Frequency", unit="Hz", min_value=1)
        >>> {key: value for key, value in PwmConfig.describe()[0].items() if value}
        {'name': 'pwm_frequency', 'type': 'int', 'label': 'PWM Frequency', 'unit': 'Hz', 'min_value': 1}
        >>> PwmConfig.from_settings({"pwm_frequency": "0"})
        Traceback (most recent call last):
            ...
        ValueError: pwm_frequency: 0 is lower than the minimum, 1

    """
    metadata = {
        "optional": optional,
        "label": label,
        "help_text": help_text,
        "choices": choices,
        "unit": unit,
        "min_value": min_value,
        "max_value": max_value,
        "visible_if": visible_if,
        "widget": widget,
    }
    return dataclass_field(default=default, compare=compare, metadata=metadata)


def _parse_str_set(value: object) -> frozenset[str]:
    """Read a saved list of strings, with at least one, as a set."""
    if not isinstance(value, (list, tuple, set, frozenset)) or not all(isinstance(item, str) for item in value):
        msg = f"not a list of strings: {value!r}"
        raise ValueError(msg)
    if not value:
        msg = "the list is empty"
        raise ValueError(msg)
    return frozenset(value)


@dataclass(frozen=True)
class _FieldType:
    """Describes a type a field of a configuration can have."""

    name: str
    """The name of the type."""

    parse: Callable[[Any], Any]
    """The function that reads a saved value of the type."""


_FIELD_TYPES: dict[Any, _FieldType] = {
    str: _FieldType(name="str", parse=str),
    int: _FieldType(name="int", parse=int),
    float: _FieldType(name="float", parse=parse_float),
    Optional[float]: _FieldType(name="float", parse=parse_float),
    bool: _FieldType(name="bool", parse=parse_bool),
    HexInt: _FieldType(name="HexInt", parse=parse_hex),
    Rgb: _FieldType(name="Rgb", parse=parse_hex_color),
    FrozenSet[str]: _FieldType(name="FrozenSet[str]", parse=_parse_str_set),
    SensorInputId: _FieldType(name="SensorInputId", parse=int),
    GpioInputId: _FieldType(name="GpioInputId", parse=int),
    OutputId: _FieldType(name="OutputId", parse=int),
    ActionId: _FieldType(name="ActionId", parse=int),
}
"""The types a field of a configuration can have."""


@dataclass(frozen=True)
class BaseConfig:
    """A configuration read from settings: each field reads the key with its name."""

    type_help: ClassVar[str] = ""
    """The help text of the type (can also contain HTML)."""

    @classmethod
    def from_settings(cls, settings: dict) -> Self:
        """Read the configuration from settings.

        A key that is missing, empty or null leaves an optional field empty: an empty text for a text, None for the
        others. Every other field needs its key.

        Args:
            settings (dict): The settings to read.

        Returns:
            Self: The configuration.

        Raises:
            TypeError: If a field has a type that can't be read from settings.
            ValueError: If a key is missing, empty or null and its field is not optional, or its value is not valid
                for its field or for the configuration.

        Examples:
            >>> @dataclass(frozen=True)
            ... class I2cConfig(BaseConfig):
            ...     temp_sensor_address: HexInt = setting()
            ...     label: str = setting(optional=True)
            >>> I2cConfig.from_settings({"temp_sensor_address": "38", "label": "Enclosure"})
            I2cConfig(temp_sensor_address=56, label='Enclosure')
            >>> I2cConfig.from_settings({"temp_sensor_address": "38"})
            I2cConfig(temp_sensor_address=56, label='')
            >>> I2cConfig.from_settings({"label": "Enclosure"})
            Traceback (most recent call last):
                ...
            ValueError: temp_sensor_address is not set

        """
        type_hints = get_type_hints(cls)
        values = {}

        for field in fields(cls):
            type_hint = type_hints[field.name]
            if type_hint in _FIELD_TYPES:
                parse = _FIELD_TYPES[type_hint].parse
            elif isinstance(type_hint, type) and issubclass(type_hint, Enum):
                parse = type_hint
            else:
                msg = f"{field.name} has a type that can't be read from settings: {type_hint}"
                raise TypeError(msg)

            value = settings.get(field.name, "")
            if value == "" or value is None:
                if not field.metadata.get("optional", False):
                    msg = f"{field.name} is not set"
                    raise ValueError(msg)

                # An optional field left empty is an empty text, or None if it is not a text
                values[field.name] = "" if type_hint is str else None
                continue

            try:
                parsed_value = parse(value)
            except (TypeError, ValueError, OverflowError) as error:
                msg = f"{field.name}: {error}"
                raise ValueError(msg) from error

            minimum = field.metadata.get("min_value")
            if minimum is not None and parsed_value < minimum:
                msg = f"{field.name}: {parsed_value} is lower than the minimum, {minimum}"
                raise ValueError(msg)

            maximum = field.metadata.get("max_value")
            if maximum is not None and parsed_value > maximum:
                msg = f"{field.name}: {parsed_value} is higher than the maximum, {maximum}"
                raise ValueError(msg)

            values[field.name] = parsed_value

        return cls(**values)

    @classmethod
    def describe(cls) -> list[dict[str, Any]]:
        """Describe the fields of the configuration.

        Returns:
            list[dict[str, Any]]: The description of each field, in order, with these keys:

                - "name" (str): The name of the field.
                - "type" (str): The name of the type of the field, or "Enum" for an enumeration.
                - "optional" (bool): Whether the field can be left empty.
                - "default" (Any): The value of the field in a new item, as it is saved, None if it starts empty.
                - "label" (str): The label, empty if not declared.
                - "help_text" (str): The help text, empty if not declared.
                - "choices" (list[list[Any]] | None): The values the field can be set to, each with its label, None
                  if it can have any value.
                - "unit" (str): The unit of the value, empty if not declared.
                - "min_value" (float | None): The lowest accepted value, None if not declared.
                - "max_value" (float | None): The highest accepted value, None if not declared.
                - "visible_if" (Mapping[str, Sequence[Any]] | None): When the field is used: for each field it names,
                  the values that field can have. None if not declared.
                - "widget" (str): The widget, empty if not declared.

        """
        type_hints = get_type_hints(cls)
        descriptions = []

        for field in fields(cls):
            type_hint = type_hints[field.name]
            type_name = _FIELD_TYPES[type_hint].name if type_hint in _FIELD_TYPES else "Enum"
            default = None if field.default is MISSING or field.default is _NO_DEFAULT else field.default
            if isinstance(default, Enum):
                default = default.value
            elif isinstance(default, Rgb):
                default = format_hex_color(default)

            choices = field.metadata.get("choices")
            if choices is None and isinstance(type_hint, type) and issubclass(type_hint, LabeledEnum):
                choices = list(type_hint)
            if choices is not None:
                choices = [[choice.value, choice.label] for choice in choices]

            descriptions.append(
                {
                    "name": field.name,
                    "type": type_name,
                    "optional": field.metadata.get("optional", False),
                    "default": default,
                    "label": field.metadata.get("label", ""),
                    "help_text": field.metadata.get("help_text", ""),
                    "choices": choices,
                    "unit": field.metadata.get("unit", ""),
                    "min_value": field.metadata.get("min_value"),
                    "max_value": field.metadata.get("max_value"),
                    "visible_if": field.metadata.get("visible_if"),
                    "widget": field.metadata.get("widget", ""),
                },
            )

        return descriptions

    def get_linked_ids(self, id_type: type[_IdT]) -> list[_IdT]:
        """Get the ids of a certain type that the configuration is linked to.

        Args:
            id_type (type[_IdT]): The type of the ids, e.g. OutputId.

        Returns:
            list[_IdT]: The value of each field of that type.

        Examples:
            >>> from octoprint_enclosure.automations.reactions.run_action import RunActionConfig
            >>> config = RunActionConfig.from_settings({"reaction_type": "run_action", "action": 3})
            >>> config.get_linked_ids(ActionId)
            [3]
            >>> config.get_linked_ids(OutputId)
            []

        """
        type_hints = get_type_hints(type(self))
        return [getattr(self, field.name) for field in fields(self) if type_hints[field.name] is id_type]
