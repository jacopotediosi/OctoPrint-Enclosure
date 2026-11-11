from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from flask import make_response

from octoprint_enclosure.actions import Action, ActionError

from .base import BaseApi
from .responses import ErrorResponse, ItemResponse, error_response, item_response, list_response
from .routes import route

if TYPE_CHECKING:
    from flask import Response

    from octoprint_enclosure.actions import Actions
    from octoprint_enclosure.plugin_context import PluginContext


@dataclass(frozen=True)
class ActionResponse(ItemResponse):
    """An action, e.g. a G-code or shell script."""

    @classmethod
    def from_action(cls, action: Action) -> ActionResponse:
        """Describe an action.

        Args:
            action (Action): The action.

        Returns:
            ActionResponse: The action.

        """
        config = action.config
        return cls(id=config.index_id, type=config.action_type, label=config.label)


class ActionsApi(BaseApi):
    """The HTTP API of the actions."""

    _actions: Actions

    def __init__(self, plugin_context: PluginContext) -> None:
        """Set up the API.

        Args:
            plugin_context (PluginContext): The plugin context.

        """
        super().__init__(plugin_context)
        self._actions = plugin_context.actions

    @route("GET", "/actions", responses={200: [ActionResponse]})
    def get_actions(self) -> Response:
        """List the actions."""
        return list_response(ActionResponse.from_action(action) for action in self._actions.get_all(Action))

    @route("GET", "/actions/<int:action_id>", responses={200: ActionResponse, 404: ErrorResponse})
    def get_action(self, action_id: int) -> Response:
        """Get an action."""
        try:
            action = self._actions.get(action_id, Action)
        except ActionError:
            return error_response(404, f"No action is set up with id {action_id}.")

        return item_response(ActionResponse.from_action(action))

    @route(
        "POST",
        "/actions/<int:action_id>/run",
        responses={204: None, 404: ErrorResponse, 409: ErrorResponse},
    )
    def run_action(self, action_id: int) -> Response:
        """Run an action."""
        try:
            action = self._actions.get(action_id, Action)
        except ActionError:
            return error_response(404, f"No action is set up with id {action_id}.")

        try:
            action.run()
        except ActionError as error:
            return error_response(409, f"Action {action_id} can't be run: {error}.")

        return make_response("", 204)
