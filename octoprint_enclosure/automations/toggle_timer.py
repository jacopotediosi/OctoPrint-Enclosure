from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.outputs import OutputSetpointConfig
from octoprint_enclosure.settings import OutputId, setting

from .base import Automation, AutomationConfig

if TYPE_CHECKING:
    import logging
    from collections.abc import Sequence

    from .conditions import Condition


@dataclass(frozen=True)
class ToggleTimerConfig(AutomationConfig, OutputSetpointConfig):
    """The configuration of an automation that turns an output on and off in turn."""

    type_help = (
        '<span class="label label-info">Info:</span> Turns an output on and off in turn, on for the on time and off '
        "for the off time."
    )

    output: OutputId = setting(label="Controlled IO", help_text="Output to turn on and off in turn.")
    """The id of the output to control."""

    toggle_timer_on: float = setting(label="On Time", help_text="Seconds the output stays on.", unit="s")
    """The seconds the output stays on."""

    toggle_timer_off: float = setting(label="Off Time", help_text="Seconds the output stays off.", unit="s")
    """The seconds the output stays off."""

    def __post_init__(self) -> None:
        """Check the automation configuration.

        Raises:
            ValueError: If the automation configuration is not valid.

        """
        if self.toggle_timer_on <= 0 or self.toggle_timer_off <= 0:
            msg = (
                "toggle_timer_on and toggle_timer_off must be above 0, "
                f"not {self.toggle_timer_on} and {self.toggle_timer_off}"
            )
            raise ValueError(msg)
        super().__post_init__()


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
