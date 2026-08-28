"""Expose the recommendation pipeline.

The agents self-instantiate at module scope with no external clients: the
feature store is built without a Redis client (its methods return empty results
in that case), and the product catalogue is upstream's own `MOCK_PRODUCTS`. So
building the graph is upstream's `build_recommendation_graph()` unchanged, after
the egress guard is installed.
"""

from __future__ import annotations

import benchmark_mocks

_compiled = None


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install_all()
        from orchestrator.graph import build_recommendation_graph

        _compiled = build_recommendation_graph()
    return _compiled
