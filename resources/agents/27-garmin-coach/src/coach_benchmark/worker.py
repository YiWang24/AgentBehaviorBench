"""JSONL worker for the training analysis workflow."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
import uuid


def _question(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("question", "query", "prompt", "input", "text", "content", "analysis_context"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found
        messages = value.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict) and isinstance(last.get("content"), str):
                return last["content"]
    return json.dumps(value, ensure_ascii=False)


def _first_text(*values) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, str) and nested.strip():
                    return nested
    return ""


def main() -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    limit = int(os.environ.get("COACH_RECURSION_LIMIT", "30"))

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
            with contextlib.redirect_stdout(sys.stderr):
                # The nodes are async-only; compiled.invoke() raises.
                state = asyncio.run(compiled.ainvoke(
                    graph_module.initial_state(question),
                    config={
                        "recursion_limit": limit,
                        # The workflow compiles with a MemorySaver, so each
                        # request needs its own thread; runs must not share
                        # one athlete's analysis with another.
                        "configurable": {"thread_id": str(uuid.uuid4())},
                    },
                ))
            answer = _first_text(
                state.get("analysis_html"),
                state.get("synthesis_result"),
                state.get("metrics_summary"),
            )
            reply = {
                "ok": True,
                "output": answer,
                "raw_output": {
                    "answer": answer,
                    "question": question,
                    "synthesis": state.get("synthesis_result"),
                    "metrics_summary": state.get("metrics_summary"),
                    "physiology_summary": state.get("physiology_summary"),
                    "activity_summary": state.get("activity_summary"),
                    "athlete": state.get("athlete_name"),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
