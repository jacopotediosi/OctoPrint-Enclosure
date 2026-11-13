from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING

import octoprint.plugin
from flask import request
from werkzeug.exceptions import BadRequest

from .bodies import BodyError
from .responses import ErrorResponse, error_response

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

    rule: str
    """The path of the route, with its parameters as Flask writes them."""

    permission: PluginPermission
    """The permission the requests need."""

    body: type[Body] | None
    """The body of the requests, or None if the route takes none."""

    responses: Mapping[int, object]
    """What the route answers, by HTTP status code: a response class, a list with one for a JSON list of it, or None
    for an empty response."""

    function: Callable[..., Response]
    """The method that handles the requests."""


ROUTES: list[Route] = []
"""The API routes."""


def route(
    method: str,
    rule: str,
    *,
    permission: PluginPermission,
    body: type[Body] | None = None,
    responses: Mapping[int, object],
) -> Callable[[Callable[..., Response]], Callable[..., Response]]:
    """Make a method an API route.

    Args:
        method (str): The HTTP method.
        rule (str): The path of the route, with its parameters as Flask writes them.
        permission (PluginPermission): The permission the requests need.
        body (type[Body] | None): The body of the requests, read from their JSON and passed to the method as `body`,
            or None if the route takes none.
        responses (Mapping[int, object]): What the route answers, by HTTP status code: a response class, a list with
            one for a JSON list of it, or None for an empty response. The answers to a missing permission and to a
            body that is not valid don't need to be listed.

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

        all_responses = {**responses, 403: ErrorResponse}
        if body is not None:
            all_responses.update({400: ErrorResponse, 415: ErrorResponse, 422: ErrorResponse})

        ROUTES.append(Route(method, rule, permission, body, all_responses, function))

        return octoprint.plugin.BlueprintPlugin.route(rule, methods=[method])(wrapper)

    return decorator
