from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterator


@dataclass(frozen=True)
class _Job:
    """An action to run at a point in time."""

    job_id: str
    """The id of the job."""

    due: float
    """When the action runs, as a monotonic time."""

    priority: int
    """Decides between jobs due at the same time: the lower runs first, in the order of scheduling."""

    action: Callable[[], object]
    """What the job runs."""


class Scheduler:
    """Runs actions after a delay, one at a time on a thread of its own.

    An action runs on the thread of the scheduler, so it must return right away: a slow one delays the actions due
    after it. Slow work belongs to another thread, which the action only hands it to.
    """

    _logger: logging.Logger

    _jobs: dict[str, _Job]
    """The job waiting to run with each id."""

    _priorities: Iterator[int]
    """The priorities of the jobs to come, in the order of scheduling."""

    _condition: threading.Condition
    """Guards the jobs, and wakes the thread up when they change."""

    _thread: threading.Thread

    def __init__(self, logger: logging.Logger) -> None:
        """Set up the scheduler and start its thread.

        Args:
            logger (logging.Logger): The logger to write to.

        """
        self._logger = logger.getChild("Scheduler")
        self._jobs = {}
        self._priorities = itertools.count()
        self._condition = threading.Condition()
        self._thread = threading.Thread(target=self._run, name="EnclosureScheduler", daemon=True)
        self._thread.start()

    def schedule(self, job_id: str, delay_seconds: float, action: Callable[[], object]) -> None:
        """Run an action after a delay, in place of the job with the same id still waiting, if any.

        Args:
            job_id (str): The id of the job, to cancel it or replace it. By convention it is what the job belongs
                to, the id of that and the purpose of the job, like "output:5:auto_shutdown", so that the jobs of
                different things never share an id, and a thing has one job for each purpose.
            delay_seconds (float): How long to wait before running the action.
            action (Callable[[], object]): What to run.

        """
        with self._condition:
            self._jobs[job_id] = _Job(job_id, time.monotonic() + delay_seconds, next(self._priorities), action)
            self._condition.notify()

    def cancel(self, job_id: str) -> None:
        """Cancel the job with an id.

        Args:
            job_id (str): The id of the job.

        """
        with self._condition:
            if self._jobs.pop(job_id, None) is not None:
                self._condition.notify()

    def cancel_all(self) -> None:
        """Cancel every job still waiting."""
        with self._condition:
            self._jobs.clear()
            self._condition.notify()

    def _run(self) -> None:
        while True:
            with self._condition:
                if not self._jobs:
                    self._condition.wait()
                    continue
                job = min(self._jobs.values(), key=lambda job: (job.due, job.priority))
                delay = job.due - time.monotonic()
                if delay > 0:
                    self._condition.wait(min(delay, threading.TIMEOUT_MAX))
                    continue
                del self._jobs[job.job_id]

            try:
                job.action()
            except Exception:
                self._logger.exception("Error running the scheduled job %s", job.job_id)
