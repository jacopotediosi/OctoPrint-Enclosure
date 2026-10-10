from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.core import Settings


class NotificationProvider(ABC):
    """A service through which notifications are sent."""

    provider_id: ClassVar[str]
    """The value the notification_provider setting takes to select this provider."""

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        """Set up the service.

        Args:
            settings (Settings): The plugin settings.
            logger (logging.Logger): The logger to write to.

        """
        self._settings = settings
        self._logger = logger

    @abstractmethod
    def send(self, message: str) -> None:
        """Send a notification.

        Args:
            message (str): The text of the notification.

        """
