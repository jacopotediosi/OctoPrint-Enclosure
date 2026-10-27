from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.core import Settings


class NotificationProvider(ABC):
    """A service through which notifications are sent."""

    provider_id: ClassVar[str]
    """The value the notification_provider setting takes to select this provider."""

    _thread: ThreadPoolExecutor
    """Delivers the notifications on the notification provider thread."""

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        """Set up the service and start delivering.

        Args:
            settings (Settings): The plugin settings.
            logger (logging.Logger): The logger to write to.

        """
        self._settings = settings
        self._logger = logger
        self._thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"EnclosureNotifier-{self.provider_id}")

    def send(self, message: str) -> None:
        """Send a notification.

        Args:
            message (str): The text of the notification.

        """
        self._thread.submit(self._try_deliver, message)

    def stop(self) -> None:
        """Deliver the notifications still pending, then stop delivering."""
        self._thread.shutdown(wait=True)

    def _try_deliver(self, message: str) -> None:
        try:
            self._deliver(message)
        except Exception:
            self._logger.exception("Error delivering a notification")

    @abstractmethod
    def _deliver(self, message: str) -> None:
        """Deliver a notification through the service, raising an exception if it can't be delivered."""
