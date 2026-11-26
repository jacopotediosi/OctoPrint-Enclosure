from __future__ import annotations

from dataclasses import MISSING, Field
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, get_type_hints

from octoprint_enclosure.utils import LabeledEnum

from .field_types import (
    NO_DEFAULT,
    WIDGET_TYPES,
    HexInt,
    can_be_empty,
    get_non_optional_field_type,
    get_non_optional_type,
)

if TYPE_CHECKING:
    from .base_config import BaseConfig
    from .field_types import FieldType


def check_declarations(config_class: type[BaseConfig]) -> None:
    """Check how the fields of a configuration are declared.

    Args:
        config_class (type[BaseConfig]): The dataclass of the configuration.

    Raises:
        TypeError: If some declarations are not valid.

    """
    field_type_hints = {
        name: type_hint
        for name, type_hint in get_type_hints(config_class).items()
        if getattr(type_hint, "__origin__", None) is not ClassVar
    }
    field_names = list(field_type_hints)
    problems = []

    # Get all declared fields of the class: the inherited ones, then the ones declared in its body
    declared_fields: dict[str, Field] = {}
    for mro_class in reversed(config_class.__mro__):
        declared_fields.update(vars(mro_class).get("__dataclass_fields__", {}))
    declared_fields.update({name: value for name, value in vars(config_class).items() if isinstance(value, Field)})

    # Check type help
    type_help = vars(config_class).get("type_help", "")
    if type_help and not type_help.rstrip().endswith("."):
        problems.append("type_help has no final period")

    # Check type field name
    type_field_name = vars(config_class).get("type_field_name", "")
    if type_field_name and type_field_name not in field_names:
        problems.append(f"type_field_name is not the name of a field: {type_field_name!r}")

    # Check fields
    field_types: dict[str, FieldType] = {}
    for name, type_hint in field_type_hints.items():
        # Check type hint
        non_optional_type = get_non_optional_type(type_hint)
        try:
            field_type = get_non_optional_field_type(non_optional_type)
        except KeyError:
            problems.append(f"{name} has a type that can't be read from settings: {non_optional_type}")
            continue
        field_types[name] = field_type

        # Skip non-configuration fields
        field = declared_fields.get(name)
        if field is None or "optional" not in field.metadata:
            continue

        is_enum = isinstance(non_optional_type, type) and issubclass(non_optional_type, Enum)
        default = field.default
        has_default = default not in (MISSING, NO_DEFAULT)
        is_optional = field.metadata["optional"]
        choices = field.metadata["choices"]
        unit = field.metadata["unit"]
        min_value = field.metadata["min_value"]
        max_value = field.metadata["max_value"]
        visible_if = field.metadata["visible_if"] or {}
        widget = field.metadata["widget"]
        is_number = non_optional_type in (int, float, HexInt)
        has_limits = min_value is not None or max_value is not None

        # Limits
        if has_limits and not is_number:
            problems.append(f"{name} has limits but is not a number")
        if min_value is not None and max_value is not None and min_value > max_value:
            problems.append(f"{name} has min_value {min_value} higher than max_value {max_value}")

        # Default
        if has_default and default in ("", None):
            problems.append(f"{name} has an empty default, which is the same as no default")
        elif has_default and type(default) not in field_type.value_types:
            problems.append(f"{name} has a default that is not a value of its type: {default!r}")
        elif has_default and is_number and min_value is not None and default < min_value:
            problems.append(f"{name} has a default lower than its min_value: {default!r}")
        elif has_default and is_number and max_value is not None and default > max_value:
            problems.append(f"{name} has a default higher than its max_value: {default!r}")
        if non_optional_type is bool and choices is None and not has_default:
            problems.append(f"{name} is a bool without choices, which needs a default")

        # Optional
        allows_empty = can_be_empty(type_hint)
        if is_optional and not allows_empty:
            problems.append(f"{name} is optional but its type can't be empty, unlike str, Optional, etc.")
        if visible_if and not allows_empty:
            problems.append(f"{name} has a visible_if but its type can't be empty, unlike str, Optional, etc.")

        # Choices
        if is_enum and not issubclass(non_optional_type, LabeledEnum):
            problems.append(f"{name} is an enumeration without labels: use a LabeledEnum")
        elif choices is not None:
            try:
                choice_values = [field_type.from_saved(choice if is_enum else choice.value) for choice in choices]
                choice_labels = [choice.label for choice in choices]
            except (AttributeError, TypeError, ValueError, OverflowError):
                problems.append(f"{name} has choices that are not values it can have, each with a label")
            else:
                if not choices:
                    problems.append(f"{name} has no choices")
                if len(set(choice_values)) != len(choice_values):
                    problems.append(f"{name} has repeated choices")
                if "" in choice_labels:
                    problems.append(f"{name} has choices with empty labels")
                if len(set(choice_labels)) != len(choice_labels):
                    problems.append(f"{name} has choices with repeated labels")
                if has_default and default not in choice_values:
                    problems.append(f"{name} has a default that is not one of its choices: {default!r}")
            if has_limits:
                problems.append(f"{name} has both choices and limits")

        # Unit and widget
        if unit and (not is_number or choices is not None):
            problems.append(f"{name} has a unit but is not a number, or has choices")
        if widget and widget not in WIDGET_TYPES:
            problems.append(f"{name} has an unknown widget: {widget!r}")
        elif widget and non_optional_type not in WIDGET_TYPES[widget]:
            problems.append(f"{name} has the widget {widget!r}, which is not for its type")
        if unit and widget in ("temperature", "temperature_interval"):
            problems.append(f"{name} has a unit, but its widget shows the unit of the temperatures")

        # Visible if
        for other_name, other_values in visible_if.items():
            if other_name not in field_names[: field_names.index(name)]:
                problems.append(f"{name} is visible if {other_name}, which is not a field declared before it")
                continue

            # The values are checked with the type of the other field: without it, that field is already a problem
            other_field_type = field_types.get(other_name)
            if other_field_type is None:
                continue

            try:
                for other_value in other_values:
                    other_field_type.from_saved(other_value)
            except (TypeError, ValueError, OverflowError):
                problems.append(f"{name} is visible if {other_name} has values it can't have: {other_values!r}")
            if not other_values:
                problems.append(f"{name} has a visible_if with no values for {other_name}")

        # Texts
        help_text = field.metadata["help_text"]
        if help_text and not help_text.rstrip().endswith("."):
            problems.append(f"{name} has a help text with no final period")

    if problems:
        msg = f"{config_class.__name__} has invalid declarations: {'; '.join(problems)}"
        raise TypeError(msg)
