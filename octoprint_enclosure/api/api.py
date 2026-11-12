from __future__ import annotations

from .actions import ActionsApi
from .automations import AutomationsApi
from .inputs import InputsApi
from .outputs import OutputsApi


class Api(InputsApi, OutputsApi, ActionsApi, AutomationsApi):
    """The plugin HTTP APIs."""
