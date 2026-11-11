from __future__ import annotations

from typing import TYPE_CHECKING

import octoprint.plugin
from flask import request
from werkzeug.exceptions import HTTPException

from .responses import error_response

if TYPE_CHECKING:
    import logging

    from flask import Response

    from octoprint_enclosure.plugin_context import PluginContext


class BaseApi(octoprint.plugin.BlueprintPlugin):
    """The base of the HTTP APIs of the plugin."""

    _identifier: str
    _basefolder: str
    _logger: logging.Logger

    def __init__(self, plugin_context: PluginContext) -> None:
        """Set up the API.

        Args:
            plugin_context (PluginContext): The plugin context.

        """
        self._identifier = plugin_context.identifier
        self._basefolder = plugin_context.basefolder
        self._logger = plugin_context.logger.getChild("Api")

    @octoprint.plugin.BlueprintPlugin.errorhandler(Exception)
    def handle_unexpected_error(self, error: Exception) -> Response | HTTPException:
        """Answer a request that failed with an error no route handled.

        Args:
            error (Exception): The error.

        Returns:
            Response | HTTPException: The response of a failed request, or the error itself if it is an HTTP error.

        """
        if isinstance(error, HTTPException):
            return error

        self._logger.error("Error handling %s %s", request.method, request.path, exc_info=error)
        return error_response(500, "Unexpected error, check the log.")
