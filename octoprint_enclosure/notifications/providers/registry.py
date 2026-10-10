from __future__ import annotations

from typing import TYPE_CHECKING

from .ifttt import IftttProvider

if TYPE_CHECKING:
    from .base import NotificationProvider

NOTIFICATION_PROVIDERS: tuple[type[NotificationProvider], ...] = (IftttProvider,)
"""The services through which notifications can be sent."""
