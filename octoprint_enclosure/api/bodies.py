from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from typing import TYPE_CHECKING, Any, NewType, Optional, get_type_hints

from octoprint_enclosure.utils import Rgb, is_number, parse_hex_color

if TYPE_CHECKING:
    from collections.abc import Callable

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


_JSON_TYPES: dict[Any, tuple[str, Callable[[object], object]]] = {
    bool: ("bool", _parse_bool),
    Optional[float]: ("number or null", _parse_number_or_null),
    Percent: ("percent", _parse_percent),
    Rgb: ("hex color", _parse_hex_color),
}
"""How to name and read a JSON value, for each type a field of a body can have."""


@dataclass(frozen=True)
class Body:
    """The body of a request: each field reads the JSON attribute with its name."""

    @classmethod
    def from_json(cls, data: object) -> Self:
        """Read the body from the JSON of a request.

        Args:
            data (object): The JSON of the request.

        Returns:
            Self: The body.

        Raises:
            BodyError: If the JSON is not an object, has attributes the body doesn't know, lacks an attribute the body
                needs, or has a value that is not valid for its field or for the body.

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
            description, parse = _JSON_TYPES[type_hints[name]]
            try:
                values[name] = parse(data[name])
            except (TypeError, ValueError):
                invalid.append(f"'{name}' is not {description}")

        errors = []
        if unknown:
            errors.append("Unknown attributes: " + ", ".join(f"'{name}'" for name in unknown) + ".")
        if missing:
            errors.append("Missing attributes: " + ", ".join(f"'{name}'" for name in missing) + ".")
        if invalid:
            errors.append("Invalid attributes: " + ", ".join(invalid) + ".")

        body = None
        if not missing and not invalid:
            try:
                body = cls(**values)
            except ValueError as error:
                errors.append(str(error))

        if body is None or errors:
            raise BodyError(*errors)

        return body
