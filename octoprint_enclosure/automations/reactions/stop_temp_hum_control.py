from __future__ import annotations

from octoprint_enclosure.core import BaseConfig

from .base import Reaction


class StopTempHumControlReaction(Reaction[BaseConfig]):
    """An automation reaction that stops the temperature and humidity controls that have Auto Shutdown on."""

    config_class = BaseConfig
