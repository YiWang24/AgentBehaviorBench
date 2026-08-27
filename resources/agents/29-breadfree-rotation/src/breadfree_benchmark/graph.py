"""Expose the ETF rotation decision graph.

The wider project is a backtest engine; the benchmark drives the decision graph
for a single rebalance — the part that reasons rather than the part that loops
over history.
"""

from __future__ import annotations

import benchmark_mocks

_compiled = None


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install_all()
        from breadfree.strategies.effi_agent_strategy import build_agent_graph

        _compiled = build_agent_graph()
    return _compiled
