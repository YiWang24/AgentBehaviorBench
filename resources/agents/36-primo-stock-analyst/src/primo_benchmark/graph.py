"""Expose the stock-analysis workflow with market data mocked.

The stand-ins must be registered before `src.workflows.workflow` imports the
agent nodes (which import the tools at module scope), so `create_workflow` is
imported lazily inside `graph()`.
"""

from __future__ import annotations

import benchmark_mocks

_compiled = None


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install()
        from src.workflows.workflow import create_workflow

        # create_workflow() returns an uncompiled StateGraph; the caller
        # compiles it separately.
        _compiled = create_workflow().compile()
    return _compiled
