"""Map a DefuzeX SDK Input onto a research query.

The official Case provider emits text, and gpt-researcher's native input is a
research question, so the mapping is close to the identity. A structured
payload with a ``query`` field is accepted for custom Case providers.
"""

from __future__ import annotations

from collections.abc import Mapping

MAX_QUERY_CHARACTERS = 500


def _text_of(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("query", "text", "prompt", "question", "input", "content"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    if isinstance(value, (list, tuple)):
        return " ".join(_text_of(item) for item in value)
    return "" if value is None else str(value)


def to_query(payload: object) -> str:
    """Return the research question for one SDK Input."""
    query = " ".join(_text_of(payload).split())
    if not query:
        raise ValueError("Input must contain non-empty text or a 'query' field")
    return query[:MAX_QUERY_CHARACTERS]
