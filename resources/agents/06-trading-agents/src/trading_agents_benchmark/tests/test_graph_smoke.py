"""End-to-end local smoke test: the real TradingAgents graph, the real
default analyst set, real stockstats indicator computation on top of the
synthetic OHLCV series, and a fake chat model standing in for the deep/quick
thinking LLMs so this runs without a real model API key or Docker.

apply_patches() must run before any `tradingagents` import (see
benchmark_mocks/patches.py for why import order matters).
"""

from __future__ import annotations

import pytest

from benchmark_mocks import apply_patches

apply_patches()

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402

from trading_agents_benchmark.tests.fakes import install_fake_llms  # noqa: E402

TICKER = "NVDA"
TRADE_DATE = "2024-05-10"


@pytest.fixture()
def benchmark_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> dict:
    # TradingAgentsGraph.__init__ builds real OpenAIClient instances before
    # this test gets a chance to swap in the fake model, so OpenAIClient.get_llm()
    # needs *a* key present to construct successfully -- it is discarded and
    # replaced by _install_fake_llms() before any invocation happens, so a
    # placeholder value is fine and no real request is ever made with it.
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder-not-used")
    config = DEFAULT_CONFIG.copy()
    config["checkpoint_enabled"] = False
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["results_dir"] = str(tmp_path / "results")
    config["data_cache_dir"] = str(tmp_path / "cache")
    config["memory_log_path"] = str(tmp_path / "memory" / "trading_memory.md")
    return config


def test_full_graph_run_produces_a_rating(benchmark_config: dict) -> None:
    trading_graph = TradingAgentsGraph(debug=False, config=benchmark_config)
    install_fake_llms(trading_graph, TICKER, TRADE_DATE)

    final_state, decision = trading_graph.propagate(TICKER, TRADE_DATE)

    assert decision in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
    assert final_state["final_trade_decision"]
    assert final_state["company_of_interest"] == TICKER
    assert final_state["trade_date"] == TRADE_DATE
    # Every default analyst produced a report -- proves each of their bound
    # tools (backed by benchmark_mocks) executed without raising.
    for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report"):
        assert final_state[key]
