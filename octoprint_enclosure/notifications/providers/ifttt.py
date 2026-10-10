from __future__ import annotations

import requests
from typing_extensions import override

from .base import NotificationProvider


class IftttProvider(NotificationProvider):
    """Sends the notifications by triggering an IFTTT Webhooks event."""

    provider_id = "ifttt"

    @override
    def send(self, message: str) -> None:
        event = self._settings.notification_event_name
        api_key = self._settings.notification_api_key
        self._logger.debug("Sending IFTTT notification for event %s: %s", event, message)
        try:
            response = requests.post(
                f"https://maker.ifttt.com/trigger/{event}/with/key/{api_key}/",
                data={"value1": message},
                timeout=(3.05, 7),
            )
        except requests.exceptions.RequestException as ex:
            self._logger.warning("Could not send IFTTT notification: %s", type(ex).__name__)
        else:
            if not response.ok:
                self._logger.warning(
                    "IFTTT rejected the notification (HTTP %s): %s",
                    response.status_code,
                    response.text,
                )
