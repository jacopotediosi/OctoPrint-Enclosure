from __future__ import annotations

from dataclasses import dataclass

from typing_extensions import override

from octoprint_enclosure.settings import REQUIRED, BaseConfig

from .base import Condition


@dataclass(frozen=True)
class PrintJobConditionConfig(BaseConfig):
    """The configuration of an automation condition on the print job."""

    printing: bool = REQUIRED
    """Whether a print job must be running (True) or must not (False)."""


class PrintJobCondition(Condition[PrintJobConditionConfig]):
    """An automation condition on whether a print job is running."""

    config_class = PrintJobConditionConfig

    @override
    def is_satisfied(self, *, printing: bool) -> bool:
        return printing == self.config.printing
