"""Persistent JSONL worker for the TradingAgents benchmark adapter.

stdin   {"input": <payload>, "run_config": <object|null>}
stdout  {"ok": true, "output": <public result>, "raw_output": <diagnostic>}
stdout  {"ok": false, "error": "ErrorType: safe message"}

stdout carries JSONL and nothing else. Upstream logs and any library that
writes to stdout are redirected to stderr for the lifetime of the process.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from typing import Any


def _configure_logging() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for handler in logging.getLogger().handlers:
        stream = getattr(handler, "stream", None)
        if stream is sys.stdout:
            handler.stream = sys.stderr


def _handle(line: str) -> dict[str, Any]:
    from . import graph as graph_module
    from .inputs import to_request

    import benchmark_mocks
    from benchmark_mocks import market_data

    try:
        request = json.loads(line)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSONDecodeError: {exc}"}

    try:
        if not isinstance(request, dict) or "input" not in request:
            raise ValueError("JSONL request must contain 'input'")

        analysis_request = to_request(request["input"])
        market_data.reset_trace()
        result = graph_module.run_analysis(
            analysis_request["ticker"], analysis_request["trade_date"]
        )

        return {
            "ok": True,
            "output": {
                "ticker": result["ticker"],
                "trade_date": result["trade_date"],
                "rating": result["rating"],
                "final_trade_decision": result["final_trade_decision"],
                "reports": result["reports"],
            },
            "raw_output": {
                "resolved_from": analysis_request["request"][:500],
                "selected_analysts": list(graph_module.SELECTED_ANALYSTS),
                "report_sections": sorted(result["reports"]),
                "report_characters": {
                    key: len(value) for key, value in result["reports"].items()
                },
                "mocks_installed": benchmark_mocks.installed(),
                "mock_trace": market_data.trace_summary(),
            },
        }
    except Exception as exc:  # noqa: BLE001 - one safe error line per input
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    _configure_logging()
    stdout = sys.stdout
    for line in sys.stdin:
        if not line.strip():
            continue
        # Anything the pipeline prints belongs on stderr; stdout stays JSONL.
        with contextlib.redirect_stdout(sys.stderr):
            response = _handle(line)
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
