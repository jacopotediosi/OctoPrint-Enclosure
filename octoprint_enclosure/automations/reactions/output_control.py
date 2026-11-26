from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Sequence

from octoprint_enclosure.config import OutputId, config_field
from octoprint_enclosure.outputs import OutputSetpointConfig
from octoprint_enclosure.utils import N_, LabeledEnum, LabeledValue

from .base import Reaction, ReactionConfig


class OutputSetState(LabeledEnum):
    """What to do with an output."""

    ON = LabeledValue(value="on", label=N_("On"))
    OFF = LabeledValue(value="off", label=N_("Off"))
    TOGGLE = LabeledValue(value="toggle", label=N_("Toggle"))


@dataclass(frozen=True)
class OutputControlConfig(OutputSetpointConfig, ReactionConfig):
    """The configuration of an automation reaction that controls an output."""

    setpoint_visible_if: ClassVar[Mapping[str, Sequence[Any]]] = {
        "controlled_io_set_state": [OutputSetState.ON.value, OutputSetState.TOGGLE.value],
    }

    controlled_io: OutputId = config_field(
        label=N_("Controlled IO"),
        help_text=N_("Output to control when the event happens."),
    )
    """The id of the output to control."""

    controlled_io_set_state: OutputSetState = config_field(
        label=N_("Set Controlled IO State"),
        help_text=N_("Whether to turn the controlled IO on or off, or to toggle it, when the event happens."),
    )
    """What to do with the output."""


class OutputControlReaction(Reaction[OutputControlConfig]):
    """An automation reaction that controls an output."""

    config_class = OutputControlConfig
