from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from typing_extensions import override

from octoprint_enclosure.config import config_field
from octoprint_enclosure.utils import LabeledValue

from .base import Condition, ConditionConfig

if TYPE_CHECKING:
    from octoprint_enclosure.automations.conditions_state import ConditionsState


@dataclass(frozen=True)
class PrintJobConditionConfig(ConditionConfig):
    """The configuration of an automation condition on the print job."""

    type_help = (
        '<span class="label label-info">Info:</span> The automation acts only while a print job is running, or only '
        "while none is."
    )

    printing: bool = config_field(
        default=True,
        label="Print Job",
        choices=[
            LabeledValue(value=True, label="Only while printing"),
            LabeledValue(value=False, label="Only while not printing"),
        ],
    )
    """Whether a print job must be running (True) or must not (False)."""


class PrintJobCondition(Condition[PrintJobConditionConfig]):
    """An automation condition on whether a print job is running."""

    config_class = PrintJobConditionConfig

    @override
    def is_satisfied(self, conditions_state: ConditionsState) -> bool:
        return conditions_state.print_job_running == self.config.printing
