"""JSONL worker for the ETF rotation decision graph."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys


def _instruction(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("question", "query", "prompt", "input", "text", "content", "instruction"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found
        messages = value.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict) and isinstance(last.get("content"), str):
                return last["content"]
    return json.dumps(value, ensure_ascii=False)


def main() -> int:
    from . import graph as graph_module
    from . import market

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    lot_size = int(os.environ.get("BREADFREE_LOT_SIZE", "100"))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps({"ok": False, "error": f"JSONDecodeError: {exc}"}), flush=True)
            continue

        try:
            instruction = _instruction(payload)
            state = market.initial_state(lot_size=lot_size)
            # The graph decides from the price series; the Case's text is
            # recorded alongside the decision rather than injected into the
            # prompts, because the nodes take no free-text input.
            with contextlib.redirect_stdout(sys.stderr):
                # analyst and risk_manager are async nodes.
                result = asyncio.run(compiled.ainvoke(state))

            weights = result.get("target_weights") or {}
            analyst = result.get("analyst_output") or {}
            risk = result.get("risk_output") or {}
            summary = ", ".join(
                f"{symbol} {weight:.0%} ({market.NAMES.get(symbol, symbol)})"
                for symbol, weight in sorted(weights.items(), key=lambda kv: -kv[1])
                if weight
            ) or "no positions selected"

            reply = {
                "ok": True,
                "output": summary,
                "raw_output": {
                    "target_weights": weights,
                    "analyst_output": analyst,
                    "risk_output": risk,
                    "metrics": result.get("metrics"),
                    "positions_before": market.POSITIONS,
                    "cash": result.get("cash"),
                    "as_of": market.AS_OF,
                    "request": instruction,
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
