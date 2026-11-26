from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.config import config_field
from octoprint_enclosure.utils import LabeledEnum, LabeledValue

from .base import Action, ActionConfig


class PrinterCommand(LabeledEnum):
    """A command for the printer."""

    RESUME = LabeledValue(value="resume", label="Printer Resume")
    PAUSE = LabeledValue(value="pause", label="Printer Pause")
    CANCEL = LabeledValue(value="cancel", label="Printer Cancel")
    START = LabeledValue(value="start", label="Start Print")
    TOGGLE = LabeledValue(value="toggle", label="Printer Toggle (Connect / Pause / Resume)")
    TOGGLE_JOB = LabeledValue(value="toggle_job", label="Job Toggle (Connect / Start / Cancel)")


@dataclass(frozen=True)
class PrinterConfig(ActionConfig):
    """The configuration of an action that controls the printer."""

    printer_action: PrinterCommand = config_field(label="Printer Action")
    """The command to send to the printer."""


class PrinterAction(Action[PrinterConfig]):
    """An action that controls the printer."""

    config_class = PrinterConfig

    @override
    def run(self) -> None:
        """Send the command to the printer.

        Raises:
            Exception: If the command can't be sent.

        """
        printer_action = self.config.printer_action

        commands = {
            PrinterCommand.RESUME: self._printer.resume_print,
            PrinterCommand.PAUSE: self._printer.pause_print,
            PrinterCommand.CANCEL: self._printer.cancel_print,
            PrinterCommand.START: self._printer.start_print,
            PrinterCommand.TOGGLE: self._toggle_pause,
            PrinterCommand.TOGGLE_JOB: self._toggle_job,
        }

        self._logger.info("Run printer action %s.", printer_action.value)
        commands[printer_action]()

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
