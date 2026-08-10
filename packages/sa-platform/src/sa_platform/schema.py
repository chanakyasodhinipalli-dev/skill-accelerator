"""JSON Schema generation and validation.

Tool and skill contracts are JSON Schema. This module derives schemas from
Python callables and Pydantic models so authors declare a signature once, and
validates payloads against them (using ``jsonschema`` when installed, with a
structural fallback that covers the common cases when it is not).
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

from .errors import ValidationError

try:  # pragma: no cover - optional dependency probe
    import jsonschema as _jsonschema

    _JSONSCHEMA_AVAILABLE = True
except ImportError:  # pragma: no cover
    _jsonschema = None  # type: ignore[assignment]
    _JSONSCHEMA_AVAILABLE = False


_PRIMITIVES: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    type(None): {"type": "null"},
    Any: {},
    datetime: {"type": "string", "format": "date-time"},
    date: {"type": "string", "format": "date"},
    bytes: {"type": "string", "contentEncoding": "base64"},
}


def type_to_schema(annotation: Any) -> dict[str, Any]:
    """Translate a Python type annotation into a JSON Schema fragment."""
    if annotation is inspect.Parameter.empty:
        return {}

    if annotation in _PRIMITIVES:
        return dict(_PRIMITIVES[annotation])

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation.model_json_schema()

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"enum": [member.value for member in annotation]}

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[X] / X | None / Union[...]
    if origin is Union or origin is types.UnionType:
        non_null = [a for a in args if a is not type(None)]
        if len(non_null) == 1:
            schema = type_to_schema(non_null[0])
            if len(non_null) != len(args):
                # Represent nullability as a type union rather than anyOf —
                # simpler for the strict-tool-use validator to consume.
                existing = schema.get("type")
                if isinstance(existing, str):
                    schema["type"] = [existing, "null"]
            return schema
        return {"anyOf": [type_to_schema(a) for a in non_null]}

    if origin in (list, set, frozenset, Sequence) or annotation in (list, set):
        item = type_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item}

    if origin is tuple:
        if args and args[-1] is Ellipsis:
            return {"type": "array", "items": type_to_schema(args[0])}
        return {"type": "array", "prefixItems": [type_to_schema(a) for a in args]}

    if origin in (dict, Mapping) or annotation is dict:
        value = type_to_schema(args[1]) if len(args) == 2 else {}
        return {"type": "object", "additionalProperties": value or True}

    if origin is typing.Literal:
        return {"enum": list(args)}

    # Unresolvable annotation: accept anything rather than reject the tool.
    return {}


def schema_from_callable(
    fn: Any,
    *,
    skip: Sequence[str] = ("self", "cls", "ctx", "context"),
    strict: bool = True,
) -> dict[str, Any]:
    """Derive an ``input_schema`` from a function signature.

    Parameter descriptions are pulled from a Google-style ``Args:`` block in
    the docstring, so a well-documented function needs no schema duplication.
    """
    signature = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # noqa: BLE001 - unresolvable forward refs must not break registration
        hints = {}

    descriptions = _docstring_param_docs(inspect.getdoc(fn) or "")

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        if name in skip or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        annotation = hints.get(name, param.annotation)
        field_schema = type_to_schema(annotation)
        if name in descriptions:
            field_schema["description"] = descriptions[name]
        if param.default is not inspect.Parameter.empty:
            if isinstance(param.default, (str, int, float, bool, type(None))):
                field_schema["default"] = param.default
        else:
            required.append(name)

        properties[name] = field_schema

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    if strict:
        # Required by the API for strict tool use; also stops the model from
        # inventing parameters the implementation would silently drop.
        schema["additionalProperties"] = False
    return schema


def _docstring_param_docs(docstring: str) -> dict[str, str]:
    """Extract ``name: description`` pairs from a Google-style Args section."""
    docs: dict[str, str] = {}
    lines = docstring.splitlines()
    in_args = False
    current: str | None = None

    for raw in lines:
        line = raw.strip()
        lowered = line.lower()
        if lowered in ("args:", "arguments:", "parameters:"):
            in_args = True
            continue
        if in_args and lowered.rstrip(":") in ("returns", "raises", "yields", "examples", "note"):
            break
        if not in_args or not line:
            continue

        if ":" in line and not raw.startswith((" " * 8, "\t\t")):
            name, _, description = line.partition(":")
            name = name.split("(")[0].strip()
            if name.isidentifier():
                current = name
                docs[current] = description.strip()
                continue
        if current:  # continuation of the previous parameter's description
            docs[current] = f"{docs[current]} {line}".strip()

    return docs


def description_from_callable(fn: Any) -> str:
    """First paragraph of the docstring — the tool/skill description."""
    doc = inspect.getdoc(fn) or ""
    paragraph: list[str] = []
    for line in doc.splitlines():
        stripped = line.strip()
        if not stripped:
            break
        if stripped.lower() in ("args:", "arguments:", "parameters:", "returns:"):
            break
        paragraph.append(stripped)
    return " ".join(paragraph)


def validate_payload(
    payload: Any,
    schema: Mapping[str, Any] | None,
    *,
    label: str = "payload",
) -> None:
    """Validate ``payload`` against ``schema``, raising :class:`ValidationError`."""
    if not schema:
        return

    if _JSONSCHEMA_AVAILABLE:  # pragma: no branch
        try:
            _jsonschema.validate(instance=payload, schema=dict(schema))
        except _jsonschema.ValidationError as exc:
            raise ValidationError(
                f"{label} failed schema validation: {exc.message}",
                details={
                    "label": label,
                    "path": list(exc.absolute_path),
                    "validator": exc.validator,
                },
                cause=exc,
            ) from exc
        except _jsonschema.SchemaError as exc:  # pragma: no cover - authoring bug
            raise ValidationError(
                f"invalid JSON Schema for {label}: {exc.message}", cause=exc
            ) from exc
        return

    _validate_structural(payload, schema, label)


def _validate_structural(payload: Any, schema: Mapping[str, Any], label: str) -> None:
    """Fallback validator covering type, required, and enum.

    Not a complete JSON Schema implementation — install ``jsonschema`` for
    full coverage. This exists so the platform still rejects obviously wrong
    payloads in minimal deployments.
    """
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(payload, Mapping):
            raise ValidationError(f"{label} must be an object, got {type(payload).__name__}")
        missing = [k for k in schema.get("required", []) if k not in payload]
        if missing:
            raise ValidationError(
                f"{label} is missing required field(s): {', '.join(missing)}",
                details={"missing": missing},
            )
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unexpected = [k for k in payload if k not in properties]
            if unexpected:
                raise ValidationError(
                    f"{label} contains unexpected field(s): {', '.join(unexpected)}",
                    details={"unexpected": unexpected},
                )
        for key, sub_schema in properties.items():
            if key in payload:
                _validate_structural(payload[key], sub_schema, f"{label}.{key}")
    elif expected == "array":
        if not isinstance(payload, (list, tuple)):
            raise ValidationError(f"{label} must be an array, got {type(payload).__name__}")
    elif expected == "string" and not isinstance(payload, str):
        raise ValidationError(f"{label} must be a string, got {type(payload).__name__}")
    elif expected == "integer" and not (isinstance(payload, int) and not isinstance(payload, bool)):
        raise ValidationError(f"{label} must be an integer, got {type(payload).__name__}")
    elif expected == "number" and not isinstance(payload, (int, float)):
        raise ValidationError(f"{label} must be a number, got {type(payload).__name__}")
    elif expected == "boolean" and not isinstance(payload, bool):
        raise ValidationError(f"{label} must be a boolean, got {type(payload).__name__}")

    if "enum" in schema and payload not in schema["enum"]:
        raise ValidationError(
            f"{label} must be one of {schema['enum']}", details={"allowed": schema["enum"]}
        )


def jsonschema_available() -> bool:
    return _JSONSCHEMA_AVAILABLE


__all__ = [
    "description_from_callable",
    "jsonschema_available",
    "schema_from_callable",
    "type_to_schema",
    "validate_payload",
]
