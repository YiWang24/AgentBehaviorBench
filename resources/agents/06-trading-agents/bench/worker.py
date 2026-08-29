"""JSONL worker for TradingAgents, speaking the ABB docker-session protocol.

Protocol (agentbench/runtime/docker/session.py):
  stdin  <- {"input": <value>, "run_config": <value>}\n
  stdout -> {"ok": true, "output": <value>, "raw_output": <value>}\n

`output` stays small so any output_key mapping still works; `raw_output`
carries the full intermediate capture, which ABB serializes verbatim
(cli/result_export.py:_json_value performs no truncation).

Nothing in tradingagents/ is modified: the graph is driven exactly the way
cli/main.py drives it, which is what makes tool-node callbacks fire.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capture import FullCapture  # noqa: E402


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, default=str, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_case(value: dict, sink_path: str | None = None) -> dict:
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    ticker = value["ticker"]
    date = value["date"]
    analysts = value.get("analysts") or ["market"]
    asset_type = value.get("asset_type", "stock")

    cfg = dict(DEFAULT_CONFIG)
    cfg["max_debate_rounds"] = value.get("max_debate_rounds", 1)
    cfg["max_risk_discuss_rounds"] = value.get("max_risk_rounds", 1)

    cap = FullCapture(sink_path)
    graph = TradingAgentsGraph(analysts, config=cfg, debug=False, callbacks=[cap])

    instrument_context = graph.resolve_instrument_context(ticker, asset_type)
    init = graph.propagator.create_initial_state(
        ticker, date, asset_type=asset_type, instrument_context=instrument_context
    )
    # The callbacks argument is what extends coverage to the tool nodes;
    # propagate() omits it, which is why this driver bypasses propagate().
    args = graph.propagator.get_graph_args(callbacks=[cap])

    final: dict = {}
    for chunk in graph.graph.stream(init, **args):
        cap.on_state(chunk)
        final = chunk
    cap.close()

    decision = final.get("final_trade_decision", "")
    signal = None
    try:
        signal = graph.process_signal(decision) if decision else None
    except Exception as exc:  # signal parsing must never mask a good run
        signal = f"<signal_error: {type(exc).__name__}: {exc}>"

    state = {
        k: v for k, v in final.items() if k != "messages"
    }
    return {
        "output": {
            "ticker": ticker,
            "date": date,
            "signal": signal,
            "final_trade_decision": decision,
        },
        "raw_output": {
            "schema": "abb.tradingagents.capture.v1",
            "case": value,
            "config": {
                "llm_provider": cfg["llm_provider"],
                "quick_think_llm": cfg["quick_think_llm"],
                "deep_think_llm": cfg["deep_think_llm"],
                "data_vendors": cfg["data_vendors"],
                "max_debate_rounds": cfg["max_debate_rounds"],
                "max_risk_discuss_rounds": cfg["max_risk_discuss_rounds"],
                "temperature": cfg.get("temperature"),
            },
            "instrument_context": instrument_context,
            "graph_nodes": sorted(graph.graph.get_graph().nodes.keys()),
            "final_state": state,
            "summary": cap.summary(),
            "events": cap.events,
        },
    }


def main() -> None:
    if "--case" in sys.argv:
        path = sys.argv[sys.argv.index("--case") + 1]
        sink = sys.argv[sys.argv.index("--sink") + 1] if "--sink" in sys.argv else None
        case = json.load(open(path))
        result = run_case(case["input"], sink)
        out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
        if out:
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"ok": True, **result}, f, default=str, ensure_ascii=False, indent=2)
        print(json.dumps(result["raw_output"]["summary"], indent=2, default=str))
        return

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            result = run_case(request.get("input") or {})
            _reply({"ok": True, **result})
        except Exception as exc:
            _reply({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-2000:],
            })


if __name__ == "__main__":
    main()
