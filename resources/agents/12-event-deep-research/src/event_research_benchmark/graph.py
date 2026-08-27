"""LangGraph entry point for the benchmark adaptation of the event researcher.

Upstream declares five graphs; the benchmark selects `supervisor`, the top-level
pipeline that drives the others. Its loop is preserved: the supervisor decides
between researching, reflecting, and finishing, and a final node structures the
gathered events into a chronology.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from src.graph import graph as _graph  # noqa: E402

RECURSION_LIMIT = 40


def graph():
    """Zero-argument factory returning the compiled supervisor graph."""
    return _graph


def _event_dict(event: Any) -> dict[str, Any]:
    dump = getattr(event, "model_dump", None)
    return dump() if callable(dump) else {"event": str(event)}


async def run_research(subject: str, run_config: dict | None = None) -> dict[str, Any]:
    """Research one subject and normalize the public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)

    state = await _graph.ainvoke({"person_to_research": subject}, config=config)

    events = state.get("structured_events") or []
    categories = state.get("existing_events") or {}
    if hasattr(categories, "model_dump"):
        categories = categories.model_dump()

    return {
        "subject": subject,
        "events": [_event_dict(event) for event in events],
        "events_summary": state.get("events_summary") or "",
        "categories": sorted(categories) if isinstance(categories, dict) else [],
        "iterations": state.get("iteration_count", 0),
    }
