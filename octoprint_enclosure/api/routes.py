from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

import octoprint.plugin
from flask import request
from werkzeug.exceptions import BadRequest

from .bodies import BodyError
from .responses import error_response

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from flask import Response

    from octoprint_enclosure.permissions import PluginPermission

    from .bodies import Body


@dataclass(frozen=True)
class Route:
    """An API route."""

    method: str
    """The HTTP method."""

    path: str
    """The path of the route, with its parameters as Flask writes them, e.g. `/outputs/<int:output_id>`."""

    permission: PluginPermission
    """The permission the requests need."""

    body: type[Body] | None
    """The body of the requests, or None if the route takes none."""

    responses: Mapping[int, object]
    """The successful responses, by HTTP status code. Each value is the body: a response class, a list with a
    response class for a JSON list, `dict` for any JSON object, or None for no body."""

    errors: Mapping[int, str]
    """Why the route refuses a request, by HTTP status code. The body of the answer is always an `ErrorResponse`."""

    function: Callable[..., Response]
    """The method that handles the requests."""


ROUTES: list[Route] = []
"""The API routes."""


def route(
    method: str,
    path: str,
    *,
    permission: PluginPermission,
    body: type[Body] | None = None,
    responses: Mapping[int, object],
    errors: Mapping[int, str] | None = None,
) -> Callable[[Callable[..., Response]], Callable[..., Response]]:
    """Make a method an API route.

    Args:
        method (str): The HTTP method.
        path (str): The path of the route, with its parameters as Flask writes them, e.g. `/outputs/<int:output_id>`.
        permission (PluginPermission): The permission the requests need.
        body (type[Body] | None): The body of the requests, read from their JSON and passed to the method as `body`,
            or None if the route takes none.
        responses (Mapping[int, object]): The successful responses, by HTTP status code. Each value is the body: a
            response class, a list with a response class for a JSON list, `dict` for any JSON object, or None for no
            body.
        errors (Mapping[int, str] | None): Why the method refuses a request, by HTTP status code, or None if it
            refuses none. A missing permission and a body that is not valid don't need to be listed.

    Returns:
        Callable[[Callable[..., Response]], Callable[..., Response]]: The decorator of the method.

    """

    def decorator(function: Callable[..., Response]) -> Callable[..., Response]:
        @functools.wraps(function)
        def wrapper(*args: object, **kwargs: object) -> Response:
            octoprint_permission = permission.to_octoprint()
            if not octoprint_permission.can():
                return error_response(403, f'The permission "{octoprint_permission.get_name()}" is needed.')

            if body is None:
                return function(*args, **kwargs)

            if not request.is_json:
                return error_response(415, "Content-Type is not json")
            try:
                data = request.get_json()
            except BadRequest:
                return error_response(400, "Malformed request")
            try:
                parsed_body = body.from_json(data)
            except BodyError as error:
                return error_response(422, *error.args)

            return function(*args, **kwargs, body=parsed_body)

        all_errors = {403: "The user doesn't have the permission."}
        if body is not None:
            all_errors[400] = "The body is not valid JSON."
            all_errors[415] = "The Content-Type is not application/json."
            all_errors[422] = "The body is not a JSON object, or its attributes are unknown, missing or not valid."
        all_errors.update(errors or {})

        ROUTES.append(Route(method, path, permission, body, responses, all_errors, function))

        return octoprint.plugin.BlueprintPlugin.route(path, methods=[method])(wrapper)

    return decorator
