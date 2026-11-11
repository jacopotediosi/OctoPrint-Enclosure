from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from flask import jsonify, make_response

if TYPE_CHECKING:
    from collections.abc import Iterable

    from flask import Response


@dataclass(frozen=True)
class ItemResponse:
    """An item, e.g. an input, output, action or automation."""

    id: int
    """The id of the item, unique among the items of its kind."""

    type: str
    """The type of the item."""

    label: str
    """The label given to the item."""


@dataclass(frozen=True)
class ErrorResponse:
    """Why a request failed."""

    errors: list[str]
    """The problems found in the request, one message each."""


def item_response(item: ItemResponse) -> Response:
    """Build the response with an item.

    Args:
        item (ItemResponse): The item.

    Returns:
        Response: The response, with the item as a JSON object.

    """
    return jsonify(asdict(item))


def list_response(items: Iterable[ItemResponse]) -> Response:
    """Build the response with a list of items.

    Args:
        items (Iterable[ItemResponse]): The items.

    Returns:
        Response: The response, with the items as a JSON list ordered by id.

    """
    return jsonify([asdict(item) for item in sorted(items, key=lambda item: item.id)])


def error_response(status: int, *errors: str) -> Response:
    """Build the response of a failed request.

    Args:
        status (int): The HTTP status code.
        *errors (str): The problems found in the request, one message each.

    Returns:
        Response: The response, with the messages in a JSON object.

    """
    return make_response(jsonify(asdict(ErrorResponse(list(errors)))), status)
