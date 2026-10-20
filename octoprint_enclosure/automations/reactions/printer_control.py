from __future__ import annotations

from dataclasses import dataclass

from octoprint_enclosure.core import BaseConfig

from .base import Reaction


@dataclass(frozen=True)
class PrinterControlConfig(BaseConfig):
    """The configuration of an automation reaction that controls the printer."""

    printer_action: str
    """What to do: "pause", "resume", "cancel", "start", "toggle", "toggle_job" or "stop_temp_hum_control"."""


class PrinterControlReaction(Reaction[PrinterControlConfig]):
    """An automation reaction that controls the printer."""

    config_class = PrinterControlConfig
