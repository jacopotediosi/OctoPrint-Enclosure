from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.settings import REQUIRED, BaseConfig

from .base import Condition

if TYPE_CHECKING:
    from octoprint_enclosure.automations.conditions_state import ConditionsState


@dataclass(frozen=True)
class PrintJobConditionConfig(BaseConfig):
    """The configuration of an automation condition on the print job."""

    printing: bool = REQUIRED
    """Whether a print job must be running (True) or must not (False)."""


class PrintJobCondition(Condition[PrintJobConditionConfig]):
    """An automation condition on whether a print job is running."""

    config_class = PrintJobConditionConfig

    @override
    def is_satisfied(self, conditions_state: ConditionsState) -> bool:
        return conditions_state.print_job_running == self.config.printing
