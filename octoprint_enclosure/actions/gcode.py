from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Action


@dataclass(frozen=True)
class GcodeConfig(BaseConfig):
    """The configuration of an action that sends G-code to the printer."""

    gcode: str = ""
    """The G-code to send."""


class GcodeAction(Action[GcodeConfig]):
    """An action that sends G-code to the printer."""

    config_class = GcodeConfig

    @override
    def run(self) -> None:
        """Send the G-code to the printer.

        Raises:
            Exception: If the G-code can't be sent.

        """
        lines = [line.strip() for line in self.config.gcode.split("\n") if line.strip()]
        self._logger.debug("Sending GCODE commands: %s", lines)
        self._printer.commands(lines)
