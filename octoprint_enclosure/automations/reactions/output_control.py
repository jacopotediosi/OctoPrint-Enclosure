from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from octoprint_enclosure.outputs import OutputSetpointConfig
from octoprint_enclosure.settings import REQUIRED

from .base import Reaction


class OutputSetState(Enum):
    """What to do with an output."""

    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"


@dataclass(frozen=True)
class OutputControlConfig(OutputSetpointConfig):
    """The configuration of an automation reaction that controls an output."""

    controlled_io: int = REQUIRED
    """The id of the output to control."""

    controlled_io_set_state: OutputSetState = REQUIRED
    """What to do with the output."""


class OutputControlReaction(Reaction[OutputControlConfig]):
    """An automation reaction that controls an output."""

    config_class = OutputControlConfig
