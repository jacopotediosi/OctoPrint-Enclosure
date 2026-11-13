"""Build the OpenAPI documentation of the plugin APIs. Run this script within the OctoPrint venv."""

from __future__ import annotations

import ast
import inspect
import json
import re
import sys
import types
import typing
from dataclasses import MISSING, fields
from pathlib import Path

import octoprint_enclosure
from octoprint_enclosure.api.api import OPENAPI_PATH, Api
from octoprint_enclosure.api.bodies import JSON_TYPES, Body
from octoprint_enclosure.api.responses import ErrorResponse
from octoprint_enclosure.api.routes import ROUTES
from octoprint_enclosure.permissions import PluginPermission, get_additional_permissions

if typing.TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from octoprint_enclosure.api.routes import Route

REPO_ROOT = Path(__file__).resolve().parent.parent
"""The folder of the repository."""

PLUGIN_IDENTIFIER = "enclosure"
"""The identifier OctoPrint gives to the plugin."""

OPENAPI_VERSION = "3.1.0"
"""The version of the OpenAPI Specification the documentation follows."""

DEFAULT_OCTOPRINT_URL = "http://127.0.0.1:5000"
"""The URL of OctoPrint the documentation uses."""

SECURITY_SCHEME_NAME = "apiKey"
"""The name of the security scheme of the documentation."""

JSON_SCHEMA_TYPES: dict[object, str] = {bool: "boolean", int: "integer", float: "number", str: "string"}
"""The name JSON Schema gives to each Python type an attribute of a response can have."""

FLASK_CONVERTER_SCHEMAS: dict[str, dict[str, object]] = {
    "int": {"type": "integer"},
}
"""The JSON Schema of each Flask converter, e.g. the `int` of `<int:output_id>`."""

FLASK_PARAMETER_PATTERN = re.compile(r"<(?:(?P<converter>\w+):)?(?P<name>\w+)>")
"""A parameter in the path of a route, as Flask writes it."""


def _pyproject_value(key: str) -> str:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    (value,) = re.findall(rf'^{key} = "(.+)"$', pyproject, re.MULTILINE)
    return value


def _docstring(obj: object) -> str:
    return " ".join((inspect.getdoc(obj) or "").split())


def _field_docstrings(data_class: type) -> dict[str, str]:
    docstrings = {}
    for base in reversed(data_class.__mro__[:-1]):
        (class_definition,) = ast.parse(inspect.getsource(base)).body
        statements = typing.cast("ast.ClassDef", class_definition).body
        for statement, next_statement in zip(statements, statements[1:]):
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and isinstance(next_statement, ast.Expr)
                and isinstance(next_statement.value, ast.Constant)
                and isinstance(next_statement.value.value, str)
            ):
                docstrings[statement.target.id] = " ".join(next_statement.value.value.split())
    return docstrings


def _type_schema(annotation: object) -> dict[str, object]:
    if annotation in JSON_SCHEMA_TYPES:
        return {"type": JSON_SCHEMA_TYPES[annotation]}

    origin = typing.get_origin(annotation)
    arguments = typing.get_args(annotation)
    if origin is list:
        return {"type": "array", "items": _type_schema(arguments[0])}
    if origin in {typing.Union, types.UnionType} and len(arguments) == 2 and type(None) in arguments:
        (not_null,) = (argument for argument in arguments if argument is not type(None))
        schema = _type_schema(not_null)
        return {**schema, "type": [schema["type"], "null"]}

    msg = f"No JSON Schema is known for the type {annotation!r}"
    raise TypeError(msg)


class OpenApiDocument:
    """The OpenAPI documentation file."""

    _schemas: dict[str, dict[str, object]]
    """The schemas of the classes the routes use, by the name of their class."""

    def __init__(self) -> None:
        """Start an empty document."""
        self._schemas = {}

    def build(self) -> dict[str, object]:
        """Build the document.

        Returns:
            dict[str, object]: The document, ready to be written as JSON.

        """
        # The classes the API is made of, in the order it lists them: each with its tag, and
        # with its routes in the order it defines them
        api_classes: list[tuple[type, dict[str, object]]] = [
            (api_class, {"name": re.sub(r"Api$", "", api_class.__name__), "description": _docstring(api_class)})
            for api_class in Api.__bases__
        ]
        api_classes.append((Api, {"name": "Documentation", "description": "The documentation of the API."}))
        paths: dict[str, dict[str, object]] = {}
        for api_class, tag in api_classes:
            method_names = {getattr(member, "__wrapped__", None): name for name, member in vars(api_class).items()}
            for route in ROUTES:
                if route.function in method_names:
                    openapi_path = FLASK_PARAMETER_PATTERN.sub(r"{\g<name>}", route.path)
                    operation = self._operation(route, method_names[route.function], tag)
                    paths.setdefault(openapi_path, {})[route.method.lower()] = operation

        return {
            "openapi": OPENAPI_VERSION,
            "info": {
                "title": f"{_pyproject_value('name')} API",
                "description": self._info_description(),
                "version": _pyproject_value("version"),
            },
            "servers": [
                {
                    "url": f"{{octoprint}}/plugin/{PLUGIN_IDENTIFIER}",
                    "variables": {
                        "octoprint": {"default": DEFAULT_OCTOPRINT_URL, "description": "The URL of OctoPrint."},
                    },
                },
            ],
            "tags": [tag for _, tag in api_classes],
            "paths": paths,
            "components": {
                "schemas": self._schemas,
                "securitySchemes": {
                    SECURITY_SCHEME_NAME: {
                        "type": "apiKey",
                        "in": "header",
                        "name": "X-Api-Key",
                        "description": "An OctoPrint API key. The request has the permissions of the user of the key.",
                    },
                },
            },
        }

    def _info_description(self) -> str:
        permission_table = [
            "| Permission | Key | Description | Default groups |",
            "|---|---|---|---|",
        ]
        for permission in get_additional_permissions():
            groups = ", ".join(f"`{group}`" for group in permission["default_groups"])
            key = f"`{PluginPermission(permission['key']).octoprint_key}`"
            permission_table.append(f"| {permission['name']} | {key} | {permission['description']} | {groups} |")

        paragraphs = [
            f"The API is located at `<OctoPrint URL>/plugin/{PLUGIN_IDENTIFIER}`.",
            (
                'A failed request answers with an error status code and the body `{"errors": [string]}`, '
                "with one message for each problem found."
            ),
            "## Permissions",
            (
                "Each endpoint needs a permission of the plugin. OctoPrint gives the permissions to groups and users "
                "(OctoPrint Settings > Access Control), and a request has the permissions of its user, "
                "e.g. the user of its API key."
            ),
            "\n".join(permission_table),
            "## Push messages",
            (
                "The plugin also sends its state over the OctoPrint push websocket, as plugin messages of the plugin "
                f"`{PLUGIN_IDENTIFIER}`, to the users with the Status permission. A message has one of these "
                "attributes:"
            ),
            (
                "- `inputs`: the same list as `GET /inputs`\n"
                "- `outputs`: the same list as `GET /outputs`\n"
                "- `automations`: the same list as `GET /automations`"
            ),
        ]
        return "\n\n".join(paragraphs)

    def _operation(self, route: Route, operation_id: str, tag: dict[str, object]) -> dict[str, object]:
        (permission,) = (
            definition for definition in get_additional_permissions() if definition["key"] == route.permission.value
        )

        # The first line of the docstring of the method is the summary, the rest opens the description
        summary, _, details = (inspect.getdoc(route.function) or "").partition("\n\n")
        description = f'Needs the "{permission["name"]}" permission.'
        if details:
            description = f"{details}\n\n{description}"

        operation: dict[str, object] = {
            "tags": [tag["name"]],
            "summary": summary,
            "description": description,
            "operationId": operation_id,
            "security": [{SECURITY_SCHEME_NAME: [route.permission.octoprint_key]}],
        }

        parameters = [
            {
                "name": match["name"],
                "in": "path",
                "required": True,
                "schema": dict(FLASK_CONVERTER_SCHEMAS[match["converter"]]),
            }
            for match in FLASK_PARAMETER_PATTERN.finditer(route.path)
        ]
        if parameters:
            operation["parameters"] = parameters

        if route.body is not None:
            content: dict[str, object] = {"schema": self._schema_reference(route.body)}
            if route.body.examples:
                for example in route.body.examples.values():
                    # Try the example against the real body to raise an exception if it is wrong
                    route.body.from_json(example)
                content["examples"] = {
                    re.sub(r"\W+", "_", name.lower()): {"summary": name, "value": example}
                    for name, example in route.body.examples.items()
                }
            operation["requestBody"] = {"required": True, "content": {"application/json": content}}

        responses = {status: self._response(body_type) for status, body_type in route.responses.items()}
        for status, description in route.errors.items():
            responses[status] = {
                "description": description,
                "content": {"application/json": {"schema": self._schema_reference(ErrorResponse)}},
            }
        operation["responses"] = {str(status): responses[status] for status in sorted(responses)}
        return operation

    def _response(self, body_type: object) -> dict[str, object]:
        if body_type is None:
            return {"description": "No content."}

        if body_type is dict:
            description = "A JSON object."
            schema: dict[str, object] = {"type": "object"}
        elif isinstance(body_type, list):
            (item_class,) = body_type
            description = "A JSON list."
            schema = {"type": "array", "items": self._schema_reference(item_class)}
        else:
            description = _docstring(body_type)
            schema = self._schema_reference(typing.cast("type[DataclassInstance]", body_type))
        return {"description": description, "content": {"application/json": {"schema": schema}}}

    def _schema_reference(self, data_class: type[DataclassInstance]) -> dict[str, object]:
        name = data_class.__name__
        if name not in self._schemas:
            self._schemas[name] = self._class_schema(data_class)
        return {"$ref": f"#/components/schemas/{name}"}

    def _class_schema(self, data_class: type[DataclassInstance]) -> dict[str, object]:
        subclasses = data_class.__subclasses__()
        if subclasses:
            return {
                "description": _docstring(data_class),
                "oneOf": [self._schema_reference(subclass) for subclass in subclasses],
            }

        type_hints = typing.get_type_hints(data_class)
        docstrings = _field_docstrings(data_class)
        is_body = issubclass(data_class, Body)
        properties = {}
        required = []
        for field in fields(data_class):
            annotation = type_hints[field.name]
            property_schema = dict(JSON_TYPES[annotation].schema) if is_body else _type_schema(annotation)
            # The metadata of a field holds the JSON Schema keywords that its type doesn't tell
            property_schema.update(field.metadata)
            property_schema["description"] = docstrings[field.name]
            properties[field.name] = property_schema
            if field.default is MISSING:
                required.append(field.name)

        schema: dict[str, object] = {"type": "object", "description": _docstring(data_class), "properties": properties}
        if required:
            schema["required"] = required
        if is_body:
            # A body with an attribute it doesn't know is refused
            schema["additionalProperties"] = False
        if is_body and data_class.exactly_one_attribute:
            schema["minProperties"] = 1
            schema["maxProperties"] = 1
        return schema


if __name__ == "__main__":
    # Avoid building the documentation from a copy of the plugin installed in the OctoPrint venv, which may be outdated
    package_path = Path(octoprint_enclosure.__file__).resolve().parent
    if package_path != REPO_ROOT / "octoprint_enclosure":
        msg = (
            f"Python imports octoprint_enclosure from {package_path}, but the documentation must be built from the "
            "code of this repository. Run `pip install -e .` in this repository to fix it."
        )
        sys.exit(msg)

    # Build the documentation
    document = OpenApiDocument().build()
    OPENAPI_PATH.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
