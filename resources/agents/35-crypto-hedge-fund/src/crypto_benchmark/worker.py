"""JSONL worker for the crypto trading agent.

The graph decides from the price series in the fixture, not from free text, so
the Case's text is recorded alongside the decision. A JSON payload may override
the tickers or the as-of date.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from datetime import datetime


def _request(payload: dict) -> dict:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return {"note": value}
    if isinstance(value, dict):
        note = None
        for key in ("question", "query", "prompt", "input", "text", "content", "note"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                note = found
                break
        return {
            "note": note or "",
            "tickers": value.get("tickers"),
            "end_date": value.get("end_date"),
        }
    return {"note": ""}


def main() -> int:
    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        agent_obj = graph_module.agent()

    from utils import settings

    default_end = settings.end_date if hasattr(settings.end_date, "isoformat") else datetime(2025, 9, 4)

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
            request = _request(payload)
            tickers = request.get("tickers") or settings.signals.tickers
            end_date = default_end
            if isinstance(request.get("end_date"), str):
                try:
                    end_date = datetime.fromisoformat(request["end_date"])
                except ValueError:
                    end_date = default_end

            portfolio = {
                "cash": settings.initial_cash,
                "margin_requirement": settings.margin_requirement,
                "positions": {t: {"long": 0, "short": 0} for t in tickers},
            }

            with contextlib.redirect_stdout(sys.stderr):
                result = agent_obj.run(
                    primary_interval=settings.primary_interval,
                    tickers=tickers,
                    end_date=end_date,
                    portfolio=portfolio,
                    show_reasoning=False,
                    model_name=settings.model.name,
                    model_provider=settings.model.provider,
                    model_base_url=settings.model.base_url,
                )

            decisions = result.get("decisions")
            reply = {
                "ok": True,
                "output": json.dumps(decisions, ensure_ascii=False, default=str),
                "raw_output": {
                    "decisions": decisions,
                    "analyst_signals": result.get("analyst_signals"),
                    "tickers": tickers,
                    "as_of": str(end_date),
                    "note": request.get("note", ""),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
