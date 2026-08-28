"""Expose the LangManus workflow with the benchmark stand-ins installed."""

from __future__ import annotations

import benchmark_mocks

_compiled = None


def graph():
    """Build the compiled graph once, after the stand-ins are registered."""
    global _compiled
    if _compiled is None:
        benchmark_mocks.install()
        from src.graph.builder import build_graph

        _compiled = build_graph()
    return _compiled


def initial_state(question: str) -> dict:
    """The state ``run_agent_workflow`` builds, minus the CLI logging."""
    from src.config import TEAM_MEMBERS

    return {
        "TEAM_MEMBERS": TEAM_MEMBERS,
        "messages": [{"role": "user", "content": question}],
        "deep_thinking_mode": True,
        "search_before_planning": True,
    }
