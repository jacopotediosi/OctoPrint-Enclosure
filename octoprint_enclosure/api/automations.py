from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from octoprint_enclosure.automations import Automation, AutomationError
from octoprint_enclosure.permissions import PluginPermission

from .base import BaseApi
from .bodies import Body
from .responses import ErrorResponse, ItemResponse, error_response, item_response, list_response
from .routes import route

if TYPE_CHECKING:
    from flask import Response

    from octoprint_enclosure.automations import Automations
    from octoprint_enclosure.engine import ControlLoop
    from octoprint_enclosure.plugin_context import PluginContext
    from octoprint_enclosure.settings import Settings


@dataclass(frozen=True)
class AutomationResponse(ItemResponse):
    """An automation."""

    enabled: bool
    """Whether the automation is enabled."""

    @classmethod
    def from_automation(cls, automation: Automation) -> AutomationResponse:
        """Describe an automation.

        Args:
            automation (Automation): The automation.

        Returns:
            AutomationResponse: The automation.

        """
        config = automation.config
        return cls(
            id=config.index_id,
            type=config.automation_type,
            label=config.label,
            enabled=automation.enabled,
        )

    @classmethod
    def from_automations(cls, automations: Automations) -> list[AutomationResponse]:
        """Describe every automation.

        Args:
            automations (Automations): The automations.

        Returns:
            list[AutomationResponse]: The automations, enabled or not.

        """
        return [
            cls.from_automation(automation) for automation in automations.get_all(Automation, include_disabled=True)
        ]


@dataclass(frozen=True)
class AutomationBody(Body):
    """What to change in an automation."""

    enabled: bool
    """Whether the automation is enabled."""


class AutomationsApi(BaseApi):
    """The HTTP API of the automations."""

    _automations: Automations
    _control_loop: ControlLoop
    _settings: Settings

    def __init__(self, plugin_context: PluginContext) -> None:
        """Set up the API.

        Args:
            plugin_context (PluginContext): The plugin context.

        """
        super().__init__(plugin_context)
        self._automations = plugin_context.automations
        self._control_loop = plugin_context.control_loop
        self._settings = plugin_context.settings

    @route("GET", "/automations", permission=PluginPermission.STATUS, responses={200: [AutomationResponse]})
    def get_automations(self) -> Response:
        """List the automations."""
        return list_response(AutomationResponse.from_automations(self._automations))

    @route(
        "GET",
        "/automations/<int:automation_id>",
        permission=PluginPermission.STATUS,
        responses={200: AutomationResponse, 404: ErrorResponse},
    )
    def get_automation(self, automation_id: int) -> Response:
        """Get an automation."""
        try:
            automation = self._automations.get(automation_id, Automation)
        except AutomationError:
            return error_response(404, f"No automation is set up with id {automation_id}.")

        return item_response(AutomationResponse.from_automation(automation))

    @route(
        "PATCH",
        "/automations/<int:automation_id>",
        permission=PluginPermission.AUTOMATIONS_ENABLE,
        body=AutomationBody,
        responses={200: AutomationResponse, 404: ErrorResponse},
    )
    def set_automation(self, automation_id: int, body: AutomationBody) -> Response:
        """Enable or disable an automation."""
        try:
            automation = self._automations.get(automation_id, Automation)
        except AutomationError:
            automation = None

        if automation is None or not self._settings.set_automation_enabled(automation_id, enabled=body.enabled):
            return error_response(404, f"No automation is set up with id {automation_id}.")

        self._control_loop.set_automation_enabled(automation_id, enabled=body.enabled, wait=True)
        return item_response(AutomationResponse.from_automation(automation))
