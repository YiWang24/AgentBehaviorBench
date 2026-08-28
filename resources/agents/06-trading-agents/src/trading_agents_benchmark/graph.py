"""LangGraph entry point declared in langgraph.json.

Applies the benchmark network mocks before importing ``tradingagents`` so
this module stays import-safe even if something other than ``worker.py``
imports it directly (see benchmark_mocks/patches.py for why patch order
matters).
"""

from __future__ import annotations

from benchmark_mocks import apply_patches

apply_patches()

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402


def graph():
    """Zero-argument factory returning the compiled TradingAgents graph.

    ``debug=False`` is required, not cosmetic: the debug path calls
    LangChain's ``message.pretty_print()``, which writes straight to stdout
    and would corrupt the worker's JSONL wire protocol.
    """
    return TradingAgentsGraph(debug=False, config=DEFAULT_CONFIG.copy()).graph
