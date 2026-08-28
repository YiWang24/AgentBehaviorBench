"""JSONL worker for the web search research agent."""

from __future__ import annotations

import contextlib
import json
import os
import sys


def _question(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("research_question", "question", "query", "prompt", "input", "text", "content"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found
        messages = value.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict) and isinstance(last.get("content"), str):
                return last["content"]
    return json.dumps(value, ensure_ascii=False)


def _content(message: object) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else str(message)


def _last(state: dict, key: str) -> str:
    values = state.get(key) or []
    if isinstance(values, str):
        return values
    return _content(values[-1]) if values else ""


def main() -> int:
    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    limit = int(os.environ.get("WEBSEARCH_RECURSION_LIMIT", "40"))

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
            question = _question(payload)
            # Upstream's nodes print a coloured trace; stdout is the protocol.
            with contextlib.redirect_stdout(sys.stderr):
                state = compiled.invoke(
                    {"research_question": question},
                    config={"recursion_limit": limit},
                )
            answer = _last(state, "final_reports") or _last(state, "reporter_response")
            reply = {
                "ok": True,
                "output": answer,
                "raw_output": {
                    "report": answer,
                    "research_question": question,
                    "plan": _last(state, "planner_response"),
                    "selected_page": _last(state, "selector_response"),
                    "search_results": _last(state, "serper_response"),
                    "scraped": _last(state, "scraper_response"),
                    "review": _last(state, "reviewer_response"),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
