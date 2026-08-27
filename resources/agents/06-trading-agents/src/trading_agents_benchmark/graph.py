"""LangGraph entry point for the benchmark adaptation of TradingAgents.

The upstream workflow is preserved exactly: four analysts with their tool
loops, the bull/bear research debate, the research manager, the trader, the
three risk analysts, and the portfolio manager. Only the data layer is swapped
for deterministic fixtures and the writable paths are moved under ``/tmp``.

Import order matters. ``runtime.prepare()`` sets the ``TRADINGAGENTS_*``
overrides that ``tradingagents.default_config`` reads at import time, and
``benchmark_mocks.install()`` must patch the data layer before
``tradingagents.graph.trading_graph`` binds those callables by name.
"""

from __future__ import annotations

import copy
from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

_BENCHMARK_VENDORS = benchmark_mocks.install()

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402

SELECTED_ANALYSTS = ("market", "social", "news", "fundamentals")

REPORT_KEYS = (
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "investment_plan",
    "trader_investment_plan",
    "final_trade_decision",
)

_pipeline: TradingAgentsGraph | None = None


def benchmark_config() -> dict[str, Any]:
    """Upstream defaults with every data category routed to the fixtures."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data_vendors"] = dict(_BENCHMARK_VENDORS)
    config["tool_vendors"] = {}
    # `debug=True` pretty-prints messages to stdout, which would corrupt the
    # JSONL protocol. The pipeline is always constructed with debug off.
    config["checkpoint_enabled"] = False
    return config


def pipeline() -> TradingAgentsGraph:
    """Build the TradingAgents pipeline once per process."""
    global _pipeline
    if _pipeline is None:
        _pipeline = TradingAgentsGraph(
            selected_analysts=SELECTED_ANALYSTS,
            debug=False,
            config=benchmark_config(),
        )
    return _pipeline


def graph():
    """Zero-argument factory returning the compiled LangGraph.

    Declared in ``langgraph.json`` so the project keeps a native LangGraph
    contract. The JSONL worker drives the pipeline through :func:`run_analysis`
    instead, because the initial state has to be built by upstream's Propagator.
    """
    return pipeline().graph


def run_analysis(ticker: str, trade_date: str) -> dict[str, Any]:
    """Run the full multi-agent pipeline and normalize its public result."""
    final_state, rating = pipeline().propagate(ticker, trade_date)

    reports = {
        key: value
        for key in REPORT_KEYS
        if isinstance(value := final_state.get(key), str) and value.strip()
    }
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "rating": rating,
        "final_trade_decision": final_state.get("final_trade_decision", ""),
        "reports": reports,
    }
