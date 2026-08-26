"""Tests for the JSONL wire contract in worker.py, against the real
TradingAgents graph with a fake chat model (no API key / Docker needed).
"""

from __future__ import annotations

import json

import pytest

from benchmark_mocks import apply_patches

apply_patches()

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402

from trading_agents_benchmark import worker  # noqa: E402
from trading_agents_benchmark.tests.fakes import install_fake_llms  # noqa: E402

TICKER = "NVDA"
TRADE_DATE = "2024-05-10"


@pytest.fixture(autouse=True)
def fake_graph(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder-not-used")
    config = DEFAULT_CONFIG.copy()
    config["checkpoint_enabled"] = False
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["results_dir"] = str(tmp_path / "results")
    config["data_cache_dir"] = str(tmp_path / "cache")
    config["memory_log_path"] = str(tmp_path / "memory" / "trading_memory.md")

    trading_graph = TradingAgentsGraph(debug=False, config=config)
    install_fake_llms(trading_graph, TICKER, TRADE_DATE)

    monkeypatch.setattr(worker, "_graph_instance", trading_graph)
    yield trading_graph


def test_handle_text_input_returns_ok_with_normalized_output() -> None:
    line = json.dumps({"input": f"Should I buy {TICKER} on {TRADE_DATE}?"})

    response = worker._handle(line)

    assert response["ok"] is True
    output = response["output"]
    assert output["ticker"] == TICKER
    assert output["trade_date"] == TRADE_DATE
    assert output["rating"] in {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
    assert output["final_trade_decision"]
    for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report"):
        assert isinstance(output[key], str) and output[key]

    raw_output = response["raw_output"]
    assert isinstance(raw_output["message_count"], int)
    json.dumps(response, ensure_ascii=False)  # must be fully JSON-serializable


def test_handle_structured_object_input() -> None:
    line = json.dumps({"input": {"prompt": f"Analyze {TICKER} for {TRADE_DATE}"}})

    response = worker._handle(line)

    assert response["ok"] is True
    assert response["output"]["ticker"] == TICKER


def test_handle_missing_input_field_is_a_safe_error() -> None:
    response = worker._handle(json.dumps({"not_input": "oops"}))

    assert response["ok"] is False
    assert response["error"].startswith("ValueError:")


def test_handle_invalid_json_is_a_safe_error() -> None:
    response = worker._handle("not json{{{")

    assert response["ok"] is False
    assert "error" in response


def test_handle_never_leaks_the_api_key_env_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear-in-output")
    line = json.dumps({"input": f"Analyze {TICKER} on {TRADE_DATE}"})

    response = worker._handle(line)

    serialized = json.dumps(response)
    assert "sk-should-never-appear-in-output" not in serialized
