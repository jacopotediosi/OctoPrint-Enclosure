from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.core import BaseConfig

from .base import Action, ActionError


@dataclass(frozen=True)
class PrinterConfig(BaseConfig):
    """The configuration of an action that controls the printer."""

    printer_action: str = ""
    """What to do: "pause", "resume", "cancel", "start", "toggle" or "toggle_job"."""


class PrinterAction(Action[PrinterConfig]):
    """An action that controls the printer."""

    config_class = PrinterConfig

    @override
    def run(self) -> None:
        """Send the command to the printer.

        Raises:
            ActionError: If the printer action is not supported.
            Exception: If the command can't be sent.

        """
        printer_action = self.config.printer_action

        commands = {
            "resume": self._printer.resume_print,
            "pause": self._printer.pause_print,
            "cancel": self._printer.cancel_print,
            "start": self._printer.start_print,
            "toggle": self._toggle_pause,
            "toggle_job": self._toggle_job,
        }
        command = commands.get(printer_action)
        if command is None:
            msg = f"Unsupported printer action: {printer_action!r}"
            raise ActionError(msg)

        self._logger.info("Run printer action %s.", printer_action)
        command()

    def _toggle_pause(self) -> None:
        if self._printer.is_operational():
            self._printer.toggle_pause_print()
        else:
            self._printer.connect()

    def _toggle_job(self) -> None:
        if not self._printer.is_operational():
            self._printer.connect()
        elif self._printer.is_printing():
            self._printer.cancel_print()
        elif self._printer.is_ready():
            self._printer.start_print()
