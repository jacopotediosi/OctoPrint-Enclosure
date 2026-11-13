from __future__ import annotations

from pathlib import Path

from flask import Response

from octoprint_enclosure.permissions import PluginPermission

from .actions import ActionsApi
from .automations import AutomationsApi
from .inputs import InputsApi
from .outputs import OutputsApi
from .routes import route

OPENAPI_PATH = Path(__file__).with_name("openapi.json")
"""The OpenAPI documentation of the API."""


class Api(InputsApi, OutputsApi, ActionsApi, AutomationsApi):
    """The plugin HTTP APIs."""

    @route("GET", "/openapi.json", permission=PluginPermission.STATUS, responses={200: dict})
    def get_openapi(self) -> Response:
        """Get the OpenAPI documentation of the API."""
        return Response(OPENAPI_PATH.read_bytes(), mimetype="application/json")
