from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar, get_type_hints

from octoprint_enclosure.utils import LabeledEnum

from .declaration_checks import check_declarations
from .field_types import NO_DEFAULT, can_be_empty, get_non_optional_field_type, get_non_optional_type

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from typing_extensions import Self

    from octoprint_enclosure.utils import LabeledValue

    from .field_types import FieldType

_IdT = TypeVar("_IdT", bound=int)
_DefaultT = TypeVar("_DefaultT")


def config_field(
    *,
    default: _DefaultT = NO_DEFAULT,
    optional: bool = False,
    label: str = "",
    help_text: str = "",
    choices: Sequence[LabeledValue | LabeledEnum] | None = None,
    unit: str = "",
    min_value: float | None = None,
    max_value: float | None = None,
    visible_if: Mapping[str, Sequence[Any]] | None = None,
    widget: str = "",
    in_summary: bool = False,
    compare: bool = True,
) -> _DefaultT:
    """Declare a field of a configuration.

    Args:
        default (_DefaultT): The default value of the field. Without one, the field starts empty.
        optional (bool): Whether the field can be left empty.
        label (str): The label of the field.
        help_text (str): The help text (can also contain HTML).
        choices (Sequence[LabeledValue | LabeledEnum] | None): The values the field can be set to, in the order they
            are listed in. A LabeledEnum field takes some of its members, or None for all of them. Any other field
            takes each value with its label, as a LabeledValue, or None to accept any value.
        unit (str): The unit of the value, e.g. "Hz", "s", etc.
        min_value (float | None): The lowest value a numeric field accepts, or None for no limit.
        max_value (float | None): The highest value a numeric field accepts, or None for no limit.
        visible_if (Mapping[str, Sequence[Any]] | None): When the field is used: each of the other fields it names
            must have one of the values listed for it. None if the field is always used.
        widget (str): The widget of the field, e.g. "temperature", "textarea", etc. Empty for the default one of the
            type of the field.
        in_summary (bool): Whether the value of the field is part of the summary of the config item, e.g. its type.
        compare (bool): Whether the field counts when two configurations are compared.

    Returns:
        _DefaultT: The field, to assign in the body of the configuration dataclass.

    Examples:
        >>> @dataclass(frozen=True)
        ... class PwmConfig(BaseConfig):
        ...     pwm_frequency: int = config_field(label="PWM Frequency", unit="Hz", min_value=1)
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
        "in_summary": in_summary,
    }
    return dataclass_field(default=default, compare=compare, metadata=metadata)


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
        check_declarations(cls)

    @classmethod
    def describe(cls) -> list[dict[str, Any]]:
        """Describe the fields of the configuration.

        Returns:
            list[dict[str, Any]]: The description of each field, in order, with these keys:
                - "name" (str): The name of the field.
                - "type" (str): The name of the type of the field.
                - "optional" (bool): Whether the field can be left empty.
                - "default" (Any): The default value of the field, None if it starts empty.
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
                - "in_summary" (bool): Whether the value is part of the summary of the config item.

        """
        type_hints = get_type_hints(cls)
        descriptions = []

        for field in fields(cls):
            non_optional_type = get_non_optional_type(type_hints[field.name])
            field_type = get_non_optional_field_type(non_optional_type)
            default = None if field.default in (MISSING, NO_DEFAULT) else field_type.to_saved(field.default)

            choices = field.metadata.get("choices")
            if choices is None and isinstance(non_optional_type, type) and issubclass(non_optional_type, LabeledEnum):
                choices = list(non_optional_type)
            if choices is not None:
                choices = [[choice.value, choice.label] for choice in choices]

            descriptions.append(
                {
                    "name": field.name,
                    "type": field_type.name,
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
                    "in_summary": field.metadata.get("in_summary", False),
                },
            )

        return descriptions

    @classmethod
    def from_settings(cls, settings: dict, *, unused_field_names: Collection[str] = ()) -> Self:
        """Read the configuration from settings.

        Each field reads the key with its name:
        - A field that is not used is not read, and is left empty: one whose `visible_if` is not satisfied, or one
          named in `unused_field_names`.
        - A field that is used needs a value, unless it is optional: a key that is missing, empty or null leaves an
          optional field empty.
        - The value of a field that is used must be one of its `choices`, if it has them, and within its limits.
        - A field left empty is "" if it is a text, None otherwise.

        Args:
            settings (dict): The settings to read.
            unused_field_names (Collection[str]): The names of other fields that are not used, to leave empty.

        Returns:
            Self: The configuration.

        Raises:
            ValueError: If a key is missing, empty or null and its field is used and not optional, or its value is
                not valid for its field or for the configuration.
            TypeError: If a field named in `unused_field_names` cannot be empty.

        Examples:
            >>> @dataclass(frozen=True)
            ... class PinConfig(BaseConfig):
            ...     gpio_pin: int = config_field()
            ...     label: str = config_field(optional=True)
            >>> PinConfig.from_settings({"gpio_pin": "17", "label": "Enclosure"})
            PinConfig(gpio_pin=17, label='Enclosure')
            >>> PinConfig.from_settings({"gpio_pin": "17"})
            PinConfig(gpio_pin=17, label='')
            >>> PinConfig.from_settings({"label": "Enclosure"})
            Traceback (most recent call last):
                ...
            ValueError: gpio_pin is not set

            >>> @dataclass(frozen=True)
            ... class TimerConfig(BaseConfig):
            ...     timing: str = config_field()
            ...     at: str = config_field(visible_if={"timing": ["at"]})
            >>> TimerConfig.from_settings({"timing": "now", "at": "12:00"})
            TimerConfig(timing='now', at='')

        """
        type_hints = get_type_hints(cls)
        field_types: dict[str, FieldType] = {}
        field_values: dict[str, Any] = {}

        for description in cls.describe():
            name = description["name"]
            type_hint = type_hints[name]
            field_type = get_non_optional_field_type(type_hint)
            field_types[name] = field_type
            empty_value = "" if str in field_type.value_types else None

            if name in unused_field_names and not can_be_empty(type_hint):
                msg = f"{name} is not used but its type is not str nor Optional"
                raise TypeError(msg)

            is_used = name not in unused_field_names and all(
                field_values[other_name] in map(field_types[other_name].from_saved, other_values)
                for other_name, other_values in (description["visible_if"] or {}).items()
            )
            if not is_used:
                field_values[name] = empty_value
                continue

            saved_value = settings.get(name, "")
            if saved_value in ("", None):
                if not description["optional"]:
                    msg = f"{name} is not set"
                    raise ValueError(msg)

                field_values[name] = empty_value
                continue

            try:
                parsed_value = field_type.from_saved(saved_value)
            except (TypeError, ValueError, OverflowError) as error:
                msg = f"{name}: {error}"
                raise ValueError(msg) from error

            choices = description["choices"]
            if choices is not None and parsed_value not in [field_type.from_saved(value) for value, _ in choices]:
                msg = f"{name}: {saved_value!r} is not one of the choices"
                raise ValueError(msg)

            min_value = description["min_value"]
            if min_value is not None and parsed_value < min_value:
                msg = f"{name}: {parsed_value} is lower than the minimum, {min_value}"
                raise ValueError(msg)

            max_value = description["max_value"]
            if max_value is not None and parsed_value > max_value:
                msg = f"{name}: {parsed_value} is higher than the maximum, {max_value}"
                raise ValueError(msg)

            field_values[name] = parsed_value

        return cls(**field_values)

    def get_linked_ids(self, id_type: type[_IdT]) -> list[_IdT]:
        """Get the ids of a certain type that the configuration is linked to.

        Args:
            id_type (type[_IdT]): The type of the ids, e.g. OutputId.

        Returns:
            list[_IdT]: The value of each field of that type.

        Examples:
            >>> from octoprint_enclosure.automations.reactions.run_action import RunActionConfig
            >>> from octoprint_enclosure.config import ActionId, OutputId
            >>> config = RunActionConfig.from_settings({"reaction_type": "run_action", "action": 3})
            >>> config.get_linked_ids(ActionId)
            [3]
            >>> config.get_linked_ids(OutputId)
            []

        """
        type_hints = get_type_hints(type(self))
        return [getattr(self, field.name) for field in fields(self) if type_hints[field.name] is id_type]
