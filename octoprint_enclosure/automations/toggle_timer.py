from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.config import OutputId, config_field
from octoprint_enclosure.outputs import OutputSetpointConfig
from octoprint_enclosure.utils import N_

from .base import Automation, AutomationConfig

if TYPE_CHECKING:
    import logging
    from collections.abc import Sequence

    from .conditions import Condition


@dataclass(frozen=True)
class ToggleTimerConfig(AutomationConfig, OutputSetpointConfig):
    """The configuration of an automation that turns an output on and off in turn."""

    type_help = N_(
        '<span class="label label-info">Info:</span> Turns an output on and off in turn, on for the on time and off '
        "for the off time.",
    )

    output: OutputId = config_field(label=N_("Controlled IO"), help_text=N_("Output to turn on and off in turn."))
    """The id of the output to control."""

    toggle_timer_on: float = config_field(
        label=N_("On Time"),
        help_text=N_("Seconds the output stays on."),
        unit="s",
        min_value=1,
    )
    """The seconds the output stays on."""

    toggle_timer_off: float = config_field(
        label=N_("Off Time"),
        help_text=N_("Seconds the output stays off."),
        unit="s",
        min_value=1,
    )
    """The seconds the output stays off."""


class ToggleTimerAutomation(Automation[ToggleTimerConfig]):
    """An automation that turns an output on and off in turn."""

    config_class = ToggleTimerConfig

    _running: bool
    """Whether the output is being turned on and off in turn."""

    def __init__(self, config: ToggleTimerConfig, logger: logging.Logger, conditions: Sequence[Condition] = ()) -> None:
        """Set up the toggle timer automation.

        Args:
            config (ToggleTimerConfig): The configuration of the automation.
            logger (logging.Logger): The logger to write to.
            conditions (Sequence[Condition]): What must be true for the automation to act.

        """
        super().__init__(config, logger, conditions)
        self._running = False

    @property
    def is_running(self) -> bool:
        """Whether the output is being turned on and off in turn."""
        return self._running

    def start(self) -> None:
        """Start turning the output on and off in turn."""
        self._running = True

    def stop(self) -> None:
        """Stop turning the output on and off."""
        self._running = False
