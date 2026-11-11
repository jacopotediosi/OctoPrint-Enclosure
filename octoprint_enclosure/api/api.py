from __future__ import annotations

from typing import TYPE_CHECKING

from flask import make_response

from .actions import ActionsApi
from .automations import AutomationsApi
from .inputs import InputsApi
from .outputs import OutputsApi
from .routes import route

if TYPE_CHECKING:
    from flask import Response


class Api(InputsApi, OutputsApi, ActionsApi, AutomationsApi):
    """The plugin HTTP APIs."""

    @route("POST", "/update", responses={204: None})
    def update_ui(self) -> Response:
        """Send the state of everything to the frontend."""
        self._control_loop.update_ui()
        return make_response("", 204)
