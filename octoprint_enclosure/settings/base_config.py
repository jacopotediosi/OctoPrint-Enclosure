from __future__ import annotations

from dataclasses import MISSING, Field, dataclass, fields
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
        visible_if (Mapping[str, Sequence[Any]] | None): When the field is used: each of the other fields it names
            must have one of the values listed for it. None if the field is always used.
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

    value_type: type | tuple[type, ...]
    """The Python type of a value of the type, or the Python types if more than one."""


_FIELD_TYPES: dict[Any, _FieldType] = {
    str: _FieldType(name="str", parse=str, value_type=str),
    int: _FieldType(name="int", parse=int, value_type=int),
    float: _FieldType(name="float", parse=parse_float, value_type=(int, float)),
    Optional[float]: _FieldType(name="float", parse=parse_float, value_type=(int, float)),
    bool: _FieldType(name="bool", parse=parse_bool, value_type=bool),
    HexInt: _FieldType(name="HexInt", parse=parse_hex, value_type=int),
    Rgb: _FieldType(name="Rgb", parse=parse_hex_color, value_type=Rgb),
    FrozenSet[str]: _FieldType(name="FrozenSet[str]", parse=_parse_str_set, value_type=frozenset),
    SensorInputId: _FieldType(name="SensorInputId", parse=int, value_type=int),
    GpioInputId: _FieldType(name="GpioInputId", parse=int, value_type=int),
    OutputId: _FieldType(name="OutputId", parse=int, value_type=int),
    ActionId: _FieldType(name="ActionId", parse=int, value_type=int),
}
"""The types a field of a configuration can have."""

WIDGET_TYPES: dict[str, tuple[Any, ...]] = {
    "id": (int,),
    "octoprint_events": (FrozenSet[str],),
    "output_setpoint": (float, Optional[float], Rgb),
    "pwm_output": (OutputId,),
    "temperature": (float, Optional[float]),
    "temperature_interval": (float,),
    "textarea": (str,),
    "thermostat_sensor": (SensorInputId,),
}
"""The widgets a field can declare, each with the types of the fields it is for."""


@dataclass(frozen=True)
class BaseConfig:
    """A configuration read from settings: each field reads the key with its name."""

    type_help: ClassVar[str] = ""
    """The help text of the type (can also contain HTML)."""

    type_field_name: ClassVar[str] = ""
    """The name of the field with the type, e.g. the type of an output. Empty if no field has a type."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Check how the fields of the configuration are declared.

        Raises:
            TypeError: If some declarations are not valid.

        """
        super().__init_subclass__(**kwargs)

        type_hints = {
            name: type_hint
            for name, type_hint in get_type_hints(cls).items()
            if getattr(type_hint, "__origin__", None) is not ClassVar
        }
        names = list(type_hints)
        problems = []

        # Check type help
        type_help = vars(cls).get("type_help", "")
        if type_help and not type_help.rstrip().endswith("."):
            problems.append("type_help has no final period")

        # Check type field name
        type_field_name = vars(cls).get("type_field_name", "")
        if type_field_name and type_field_name not in names:
            problems.append(f"type_field_name is not the name of a field: {type_field_name!r}")

        # Check fields
        for name, type_hint in type_hints.items():
            # Check type hint
            is_enum = isinstance(type_hint, type) and issubclass(type_hint, Enum)
            if type_hint not in _FIELD_TYPES and not is_enum:
                problems.append(f"{name} has a type that can't be read from settings: {type_hint}")
                continue

            # The fields of the parent classes were checked with their classes
            field = vars(cls).get(name)
            if not isinstance(field, Field) or "optional" not in field.metadata:
                continue

            parse = type_hint if is_enum else _FIELD_TYPES[type_hint].parse
            default = field.default
            has_default = default is not MISSING and default is not _NO_DEFAULT
            optional = field.metadata["optional"]
            choices = field.metadata["choices"]
            unit = field.metadata["unit"]
            min_value = field.metadata["min_value"]
            max_value = field.metadata["max_value"]
            widget = field.metadata["widget"]
            is_number = type_hint in (int, float, Optional[float], HexInt)
            has_limits = min_value is not None or max_value is not None
            has_optional_type = type(None) in getattr(type_hint, "__args__", ())

            # Limits
            if has_limits and not is_number:
                problems.append(f"{name} has limits but is not a number")
            if min_value is not None and max_value is not None and min_value > max_value:
                problems.append(f"{name} has min_value {min_value} higher than max_value {max_value}")

            # Default
            if is_enum:
                is_default_of_type = isinstance(default, type_hint)
            else:
                # A bool is also an int, but it is not the value of a number
                is_default_of_type = isinstance(default, _FIELD_TYPES[type_hint].value_type)
                is_default_of_type = is_default_of_type and isinstance(default, bool) == (type_hint is bool)

            if has_default and (default == "" or default is None):
                problems.append(f"{name} has an empty default, which is the same as no default")
            elif has_default and not is_default_of_type:
                problems.append(f"{name} has a default that is not a value of its type: {default!r}")
            elif has_default and is_number and min_value is not None and default < min_value:
                problems.append(f"{name} has a default lower than its min_value: {default!r}")
            elif has_default and is_number and max_value is not None and default > max_value:
                problems.append(f"{name} has a default higher than its max_value: {default!r}")
            if type_hint is bool and choices is None and not has_default:
                problems.append(f"{name} is a bool without choices, which needs a default")

            # Optional
            if optional and type_hint is not str and not has_optional_type:
                problems.append(f"{name} is optional but its type is not str nor Optional")
            if has_optional_type and not optional:
                problems.append(f"{name} has an Optional type but is not optional")

            # Choices
            if is_enum and not issubclass(type_hint, LabeledEnum):
                problems.append(f"{name} is an enumeration without labels: use a LabeledEnum")
            elif choices is not None:
                # The choices of an enumeration are its members, the others are saved values with their label
                try:
                    choice_values = [parse(choice if is_enum else choice.value) for choice in choices]
                    choice_labels = [choice.label for choice in choices]
                except (AttributeError, TypeError, ValueError, OverflowError):
                    problems.append(f"{name} has choices that are not values it can have, each with a label")
                else:
                    if not choices:
                        problems.append(f"{name} has no choices")
                    if len(set(choice_values)) != len(choice_values):
                        problems.append(f"{name} has repeated choices")
                    if "" in choice_labels or len(set(choice_labels)) != len(choice_labels):
                        problems.append(f"{name} has choices with empty or repeated labels")
                    if has_default and default not in choice_values:
                        problems.append(f"{name} has a default that is not one of its choices: {default!r}")
                if has_limits:
                    problems.append(f"{name} has both choices and limits")

            # Unit and widget
            if unit and (not is_number or choices is not None):
                problems.append(f"{name} has a unit but is not a number, or has choices")
            if widget and widget not in WIDGET_TYPES:
                problems.append(f"{name} has an unknown widget: {widget!r}")
            elif widget and type_hint not in WIDGET_TYPES[widget]:
                problems.append(f"{name} has the widget {widget!r}, which is not for its type")
            if unit and widget in ("temperature", "temperature_interval"):
                problems.append(f"{name} has a unit, but its widget shows the unit of the temperatures")

            # Visible if
            for other_name, other_values in (field.metadata["visible_if"] or {}).items():
                if other_name not in names[: names.index(name)]:
                    problems.append(f"{name} is visible if {other_name}, which is not a field declared before it")
                    continue

                # A field with a type that can't be read is already a problem
                other_type_hint = type_hints[other_name]
                if other_type_hint in _FIELD_TYPES:
                    other_parse = _FIELD_TYPES[other_type_hint].parse
                elif isinstance(other_type_hint, type) and issubclass(other_type_hint, Enum):
                    other_parse = other_type_hint
                else:
                    continue

                try:
                    for other_value in other_values:
                        other_parse(other_value)
                except (TypeError, ValueError, OverflowError):
                    problems.append(f"{name} is visible if {other_name} has values it can't have: {other_values!r}")
                if not other_values:
                    problems.append(f"{name} is visible if {other_name} has one of no values")

            # Texts
            help_text = field.metadata["help_text"]
            if help_text and not help_text.rstrip().endswith("."):
                problems.append(f"{name} has a help text with no final period")

        if problems:
            msg = f"{cls.__name__} has invalid declarations: {'; '.join(problems)}"
            raise TypeError(msg)

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
            parse = _FIELD_TYPES[type_hint].parse if type_hint in _FIELD_TYPES else type_hint

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
                - "visible_if" (Mapping[str, Sequence[Any]] | None): When the field is used: each field it names must
                  have one of the values listed for it. None if not declared.
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
