from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from .providers import NOTIFICATION_PROVIDERS

if TYPE_CHECKING:
    import logging

    from octoprint_enclosure.core import Settings


class NotificationType(Enum):
    """A kind of event the plugin can notify. Its value is the key it is stored under in the plugin settings."""

    TEMPERATURE_ACTION = "temperatureAction"
    PRINTER_ACTION = "printer_action"
    GPIO_ACTION = "gpioAction"
    FILAMENT_CHANGE = "filamentChange"
    PRINT_FINISH = "printFinish"


class Notifications:
    """The notifications sent when something happens on the enclosure."""

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        """Set up the sending of notifications.

        Args:
            settings (Settings): The plugin settings.
            logger (logging.Logger): The logger to write to.

        """
        self._settings = settings
        self._logger = logger.getChild("Notifications")
        self._providers = {
            provider.provider_id: provider(settings, self._logger) for provider in NOTIFICATION_PROVIDERS
        }

    def send(self, notification_type: NotificationType, message: str) -> None:
        """Send a notification through the selected provider, if its type is enabled.

        Args:
            notification_type (NotificationType): The type of the notification.
            message (str): The text of the notification.

        """
        provider = self._providers.get(self._settings.notification_provider)
        if provider is None:
            return

        for notification in self._settings.notifications:
            if notification[notification_type.value]:
                provider.send(message)
