from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Sequence

from octoprint_enclosure.outputs import OutputSetpointConfig
from octoprint_enclosure.settings import OutputId, setting
from octoprint_enclosure.utils import LabeledEnum, LabeledValue

from .base import Reaction, ReactionConfig


class OutputSetState(LabeledEnum):
    """What to do with an output."""

    ON = LabeledValue(value="on", label="On")
    OFF = LabeledValue(value="off", label="Off")
    TOGGLE = LabeledValue(value="toggle", label="Toggle")


@dataclass(frozen=True)
class OutputControlConfig(OutputSetpointConfig, ReactionConfig):
    """The configuration of an automation reaction that controls an output."""

    setpoint_visible_if: ClassVar[Mapping[str, Sequence[Any]]] = {
        "controlled_io_set_state": [OutputSetState.ON.value, OutputSetState.TOGGLE.value],
    }

    controlled_io: OutputId = setting(
        label="Controlled IO",
        help_text="Output to control when the event happens.",
    )
    """The id of the output to control."""

    controlled_io_set_state: OutputSetState = setting(
        label="Set Controlled IO State",
        help_text="Whether to turn the controlled IO on or off, or to toggle it, when the event happens.",
    )
    """What to do with the output."""


class OutputControlReaction(Reaction[OutputControlConfig]):
    """An automation reaction that controls an output."""

    config_class = OutputControlConfig
