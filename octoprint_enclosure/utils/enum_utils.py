from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing_extensions import Self


@dataclass(frozen=True)
class LabeledValue:
    """A value with its label."""

    value: Any
    """The value."""

    label: str
    """The label of the value."""


class LabeledEnum(Enum):
    """An enumeration whose members have a label, besides their value.

    Examples:
        >>> class Edge(LabeledEnum):
        ...     RISE = LabeledValue(value="rise", label="Rise")
        ...     FALL = LabeledValue(value="fall", label="Fall")
        >>> Edge("fall")
        <Edge.FALL: 'fall'>
        >>> Edge.FALL.label
        'Fall'

    """

    _value_: str

    label: str
    """The label of the member."""

    def __new__(cls, labeled_value: LabeledValue) -> Self:
        """Create a member.

        Args:
            labeled_value (LabeledValue): The value and the label of the member.

        Returns:
            Self: The member.

        """
        member = object.__new__(cls)
        member._value_ = labeled_value.value
        member.label = labeled_value.label
        return member
