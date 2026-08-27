"""JSONL worker for the NL2SQL data agent."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import uuid


def _question(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("question", "query", "prompt", "input", "text", "content"):
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

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    limit = int(os.environ.get("NL2SQL_RECURSION_LIMIT", "25"))

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
                    {"question": question, "datasource_name": "benchmark_sales"},
                    config={
                        "recursion_limit": limit,
                        # compile() installs an InMemorySaver, which requires a
                        # thread. Each request gets its own, so runs do not
                        # share conversation state.
                        "configurable": {"thread_id": str(uuid.uuid4())},
                    },
                ))
            answer = state.get("final_response") or state.get("error") or ""
            reply = {
                "ok": True,
                "output": str(answer),
                "raw_output": {
                    "answer": str(answer),
                    "question": question,
                    "generated_sql": state.get("generated_sql"),
                    "rewritten_question": state.get("rewritten_question"),
                    "result": state.get("result"),
                    "error": state.get("error"),
                    "database": graph_module.database_path(),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
