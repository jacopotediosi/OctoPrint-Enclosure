from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.core import BaseConfig
from octoprint_enclosure.outputs import RegularSetState

from .base import Reaction


@dataclass(frozen=True)
class OutputControlConfig(BaseConfig):
    """The configuration of an automation reaction that controls an output."""

    controlled_io: int
    """The id of the output."""

    controlled_io_set_state: RegularSetState
    """What to do with the output."""


class OutputControlReaction(Reaction[OutputControlConfig]):
    """An automation reaction that controls an output."""

    config_class = OutputControlConfig
