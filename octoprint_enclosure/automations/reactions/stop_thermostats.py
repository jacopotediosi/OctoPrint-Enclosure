from __future__ import annotations

from octoprint_enclosure.core import BaseConfig

from .base import Reaction


class StopThermostatsReaction(Reaction[BaseConfig]):
    """An automation reaction that stops the thermostats that have Auto Shutdown on."""

    config_class = BaseConfig
