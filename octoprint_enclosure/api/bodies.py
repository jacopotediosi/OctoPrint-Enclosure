from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, NewType, Optional, get_type_hints

from octoprint_enclosure.utils import HEX_COLOR_PATTERN, Rgb, is_number, parse_hex_color

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from typing_extensions import Self


class _Unset:
    """The marker of a field whose attribute the request left out."""


UNSET: Any = _Unset()
"""The value of a field whose attribute the request left out."""

Percent = NewType("Percent", float)
"""A number from 0 to 100."""


class BodyError(Exception):
    """Raised when the body of a request is not valid. Its arguments are the problems found, one message each."""


def _parse_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError
    return value


def _parse_number(value: object) -> float:
    if not is_number(value):
        raise TypeError
    return float(value)


def _parse_number_or_null(value: object) -> float | None:
    return None if value is None else _parse_number(value)


def _parse_percent(value: object) -> float:
    number = _parse_number(value)
    if not 0 <= number <= 100:
        raise ValueError
    return number


def _parse_hex_color(value: object) -> Rgb:
    if not isinstance(value, str):
        raise TypeError
    return parse_hex_color(value)


class JsonType(NamedTuple):
    """How a field of a body reads a JSON value."""

    name: str
    """The name of the type."""

    parse: Callable[[object], object]
    """The function that reads the value."""

    schema: Mapping[str, object]
    """The JSON Schema of the values that are valid."""


JSON_TYPES: dict[Any, JsonType] = {
    bool: JsonType("bool", _parse_bool, {"type": "boolean"}),
    Optional[float]: JsonType("number or null", _parse_number_or_null, {"type": ["number", "null"]}),
    Percent: JsonType("percent", _parse_percent, {"type": "number", "minimum": 0, "maximum": 100}),
    Rgb: JsonType("hex color", _parse_hex_color, {"type": "string", "pattern": f"^{HEX_COLOR_PATTERN.pattern}$"}),
}
"""How to read a JSON value, for each type a field of a body can have."""


@dataclass(frozen=True)
class Body:
    """The body of a request: each field reads the JSON attribute with its name."""

    exactly_one_attribute: ClassVar[bool] = False
    """Whether a request must send exactly one of the attributes of the body."""

    examples: ClassVar[dict] = {}
    """Some requests the body accepts, as JSON, by what each one does, for documentation purposes."""

    @classmethod
    def from_json(cls, data: object) -> Self:
        """Read the body from the JSON of a request.

        Args:
            data (object): The JSON of the request.

        Returns:
            Self: The body.

        Raises:
            BodyError: If the JSON is not an object, has attributes the body doesn't know, lacks an attribute the body
                needs, has a value that is not valid for its field, or doesn't have exactly one attribute when the
                body takes exactly one.

        Examples:
            >>> @dataclass(frozen=True)
            ... class FanBody(Body):
            ...     duty_cycle: Percent
            >>> FanBody.from_json({"duty_cycle": 40})
            FanBody(duty_cycle=40.0)
            >>> try:
            ...     FanBody.from_json({"duty_cycle": 140, "speed": 1})
            ... except BodyError as error:
            ...     error.args
            ("Unknown attributes: 'speed'.", "Invalid attributes: 'duty_cycle' is not percent.")

        """
        if not isinstance(data, dict):
            msg = "Body is not a json object"
            raise BodyError(msg)

        type_hints = get_type_hints(cls)
        names = [field.name for field in fields(cls)]
        unknown = [name for name in data if name not in names]
        missing = [field.name for field in fields(cls) if field.name not in data and field.default is MISSING]
        invalid = []
        values = {}
        for name in names:
            if name not in data:
                continue
            json_type = JSON_TYPES[type_hints[name]]
            try:
                values[name] = json_type.parse(data[name])
            except (TypeError, ValueError):
                invalid.append(f"'{name}' is not {json_type.name}")

        errors = []
        if unknown:
            errors.append("Unknown attributes: " + ", ".join(f"'{name}'" for name in unknown) + ".")
        if missing:
            errors.append("Missing attributes: " + ", ".join(f"'{name}'" for name in missing) + ".")
        if invalid:
            errors.append("Invalid attributes: " + ", ".join(invalid) + ".")

        body = None
        if not missing and not invalid:
            if cls.exactly_one_attribute and len(values) != 1:
                attributes = ", ".join(f"'{name}'" for name in names)
                errors.append(f"Exactly one of these attributes is needed: {attributes}.")
            else:
                body = cls(**values)

        if body is None or errors:
            raise BodyError(*errors)

        return body
