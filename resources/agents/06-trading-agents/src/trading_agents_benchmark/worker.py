"""AgentBench JSONL transport for the TradingAgents graph.

Wire contract (see docs/Agents/Runtime.md):
    stdin:  {"input": <SDK payload>, "run_config": <optional object>}\n
    stdout: {"ok": true, "output": <public result>, "raw_output": <diagnostic>}\n
    stdout: {"ok": false, "error": "ErrorType: safe message"}\n
"""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from typing import Any

from benchmark_mocks import apply_patches

apply_patches()

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.graph.trading_graph import TradingAgentsGraph  # noqa: E402

from trading_agents_benchmark.input_mapping import parse_request  # noqa: E402

_graph_instance: TradingAgentsGraph | None = None


def _get_graph() -> TradingAgentsGraph:
    """Build the TradingAgentsGraph once and reuse it across requests.

    Construction creates the LLM clients and compiles the graph; reusing the
    instance avoids paying that cost per JSONL line in a persistent worker.
    ``debug=False`` keeps LangChain's ``pretty_print`` (which writes to
    stdout) out of the graph's debug streaming path.
    """
    global _graph_instance
    if _graph_instance is None:
        with redirect_stdout(sys.stderr):
            _graph_instance = TradingAgentsGraph(debug=False, config=DEFAULT_CONFIG.copy())
    return _graph_instance


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        response = _handle(line)
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def _handle(line: str) -> dict[str, Any]:
    try:
        request = json.loads(line)
        if not isinstance(request, dict) or "input" not in request:
            raise ValueError("JSONL request must contain 'input'")

        ticker, trade_date, asset_type = parse_request(request["input"])
        trading_graph = _get_graph()

        # TradingAgents' own dataflow code (and, on rare exception paths,
        # stockstats) can call print() directly; redirect_stdout keeps that
        # off the JSONL channel regardless of debug mode.
        with redirect_stdout(sys.stderr):
            final_state, decision = trading_graph.propagate(ticker, trade_date, asset_type=asset_type)

        return {
            "ok": True,
            "output": _public_output(ticker, trade_date, decision, final_state),
            "raw_output": _raw_output(final_state),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _public_output(ticker: str, trade_date: str, decision: str, state: dict) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "rating": decision,
        "final_trade_decision": _text(state.get("final_trade_decision")),
        "investment_plan": _text(state.get("investment_plan")),
        "trader_investment_plan": _text(state.get("trader_investment_plan")),
        "market_report": _text(state.get("market_report")),
        "sentiment_report": _text(state.get("sentiment_report")),
        "news_report": _text(state.get("news_report")),
        "fundamentals_report": _text(state.get("fundamentals_report")),
    }


def _raw_output(state: dict) -> dict[str, Any]:
    investment_debate = state.get("investment_debate_state") or {}
    risk_debate = state.get("risk_debate_state") or {}
    return {
        "research_manager_judge_decision": _text(investment_debate.get("judge_decision")),
        "risk_manager_judge_decision": _text(risk_debate.get("judge_decision")),
        "bull_history": _text(investment_debate.get("bull_history")),
        "bear_history": _text(investment_debate.get("bear_history")),
        "message_count": len(state.get("messages") or []),
    }


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
