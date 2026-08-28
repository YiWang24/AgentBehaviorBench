"""JSONL worker for the PrimoAgent stock analysis workflow."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import uuid
from datetime import datetime


def _request(payload: dict) -> dict:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return {"symbols": _symbols_from_text(value), "note": value}
    if isinstance(value, dict):
        note = None
        for key in ("question", "query", "prompt", "input", "text", "content", "note"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                note = found
                break
        symbols = value.get("symbols")
        if isinstance(value.get("symbol"), str):
            symbols = [value["symbol"]]
        if not symbols and note:
            symbols = _symbols_from_text(note)
        return {
            "symbols": symbols or ["BENC", "DFUZ"],
            "analysis_date": value.get("analysis_date"),
            "note": note or "",
        }
    return {"symbols": ["BENC", "DFUZ"], "note": ""}


def _symbols_from_text(text: str) -> list[str]:
    import re

    found = [t for t in re.findall(r"\b[A-Z]{2,5}\b", text or "") if t not in {"THE", "AND", "FOR"}]
    return found or ["BENC", "DFUZ"]


def main() -> int:
    from src.workflows.state import create_initial_state

    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    default_date = os.environ.get("PRIMO_DATE", "2026-08-24")

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
            symbols = request["symbols"]
            analysis_date = request.get("analysis_date") or default_date
            state = create_initial_state(str(uuid.uuid4()), symbols, analysis_date)
            with contextlib.redirect_stdout(sys.stderr):
                result = asyncio.run(compiled.ainvoke(state))

            portfolio = result.get("portfolio_manager_results")
            reply = {
                "ok": True,
                "output": json.dumps(portfolio, ensure_ascii=False, default=str),
                "raw_output": {
                    "portfolio_manager": portfolio,
                    "technical_analysis": result.get("technical_analysis_results"),
                    "news_intelligence": result.get("news_intelligence_results"),
                    "symbols": symbols,
                    "analysis_date": analysis_date,
                    "note": request.get("note", ""),
                    "error": result.get("error"),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
