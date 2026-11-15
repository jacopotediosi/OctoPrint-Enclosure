from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConditionsState:
    """The current state of the things that the automation conditions check, e.g. the print job."""

    print_job_running: bool = False
    """Whether a print job is running."""
