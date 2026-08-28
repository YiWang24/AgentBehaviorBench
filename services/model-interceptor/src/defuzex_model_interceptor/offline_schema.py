"""Synthesize a value that satisfies a JSON Schema.

An Agent that declared a tool or a response format is about to read specific
fields off the reply. A canned sentence fails on the first access, so the schema
it published is filled in with type-appropriate placeholders instead — enough
shape to keep the Agent running, with no claim to be a real answer.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

# The filler for any string the schema does not otherwise constrain, and the
# text of a reply that carries no structure at all.
OFFLINE_TEXT = "offline verification reply"


_MAX_SCHEMA_DEPTH = 4


def _resolve(field: object, root: Mapping[str, Any] | None) -> object:
    """Follow local `$ref` pointers so nested models get their real shape.

    Pydantic emits nested models as `$ref` into `$defs`, so a field that looks
    untyped is often a whole object. Only in-document pointers are followed;
    the mock never fetches a schema.
    """

    for _ in range(_MAX_SCHEMA_DEPTH + 1):
        if not isinstance(field, dict):
            return field
        reference = field.get("$ref")
        if not isinstance(reference, str) or not reference.startswith("#/"):
            return field
        if root is None:
            return field
        node: object = root
        for part in reference[2:].split("/"):
            if not isinstance(node, dict):
                return field
            node = node.get(part)
        if node is None:
            return field
        field = node
    return field


def arguments_for(
    schema: object, depth: int = 0, root: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Fill a JSON Schema's required properties with type-appropriate placeholders."""

    if root is None and isinstance(schema, dict):
        root = schema
    schema = _resolve(schema, root)
    if not isinstance(schema, dict) or depth > _MAX_SCHEMA_DEPTH:
        return {}
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict):
        return {}
    names = (
        [item for item in required if isinstance(item, str)]
        if isinstance(required, list)
        else list(properties)
    )
    return {
        name: _placeholder(properties.get(name), depth + 1, root)
        for name in names
        if name in properties
    }


def _placeholder(
    field: object, depth: int = 0, root: Mapping[str, Any] | None = None
) -> Any:
    field = _resolve(field, root)
    if not isinstance(field, dict):
        return OFFLINE_TEXT
    choices = field.get("enum")
    if isinstance(choices, list) and choices:
        return _terminal_choice(choices)

    # Optional fields arrive as anyOf[..., {"type": "null"}]; answer the first
    # branch that is not null rather than treating the field as untyped.
    for key in ("anyOf", "oneOf", "allOf"):
        branches = field.get(key)
        if isinstance(branches, list):
            for branch in branches:
                resolved = _resolve(branch, root)
                if isinstance(resolved, dict) and resolved.get("type") != "null":
                    return _placeholder(resolved, depth, root)

    kind = field.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), "string")
    if kind == "boolean":
        return True
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "array":
        # One element rather than none. An empty list satisfies the schema but
        # is not what a model would return, and agents that go straight to
        # `items[0]` fail on it — a startup check should not turn into an
        # IndexError. Nesting is bounded so a recursive schema cannot spin.
        if depth > _MAX_SCHEMA_DEPTH:
            return []
        return [_placeholder(field.get("items"), depth + 1, root)]
    if kind == "object" or isinstance(field.get("properties"), dict):
        return arguments_for(field, depth, root)
    return OFFLINE_TEXT


# Words an Agent uses for the branch that ends a run. Matched on the value with
# separators removed, so "final_report", "FINISH" and "__end__" all count.
_TERMINAL_CHOICES = frozenset(
    {
        "complete",
        "completed",
        "done",
        "end",
        "exit",
        "final",
        "finalanswer",
        "finalreport",
        "finish",
        "finished",
        "stop",
        "terminate",
    }
)


def _terminal_choice(choices: list[Any]) -> Any:
    """Pick the enum value that lets the Agent stop, else the first.

    Routing enums are the common case — a supervisor asked which worker acts
    next, with one branch meaning "we are done". Answering with the first value
    sends every offline run around the same loop until it hits the recursion
    limit, which reads as an Agent defect and is really an artefact of a mock
    that cannot decide anything. The offline reply is not a judgement about the
    work; it only has to let the Agent finish, so a terminal branch is taken
    when the Agent offers one.
    """

    for choice in choices:
        if not isinstance(choice, str):
            continue
        if re.sub(r"[^a-z0-9]", "", choice.lower()) in _TERMINAL_CHOICES:
            return choice
    return choices[0]


__all__ = ["OFFLINE_TEXT", "arguments_for"]
