from __future__ import annotations

from octoprint_enclosure.utils import LabeledEnum, LabeledValue


class Edge(LabeledEnum):
    """A change of the level of a GPIO pin: a rise from low to high, or a fall from high to low."""

    RISE = LabeledValue(value="rise", label="Rise")
    FALL = LabeledValue(value="fall", label="Fall")

    @property
    def level(self) -> int:
        """The level of a pin after the edge, 1 if high or 0 if low."""
        return _EDGE_LEVELS[self]


_EDGE_LEVELS = {Edge.RISE: 1, Edge.FALL: 0}
"""The level of a pin after each edge."""
