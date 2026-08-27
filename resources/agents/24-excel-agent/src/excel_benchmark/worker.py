"""JSONL worker for the Excel analysis agent."""

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


def _text(message: object) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


def main() -> int:
    from langchain_core.messages import HumanMessage

    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    limit = int(os.environ.get("EXCEL_RECURSION_LIMIT", "25"))

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
                state = compiled.invoke(
                    {"messages": [HumanMessage(content=question)]},
                    config={"recursion_limit": limit},
                )
            messages = state.get("messages") or []
            answer = ""
            for message in reversed(messages):
                body = _text(message).strip()
                if body:
                    answer = body
                    break
            tool_calls = []
            for message in messages:
                for call in getattr(message, "tool_calls", None) or []:
                    name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
                    args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
                    tool_calls.append({"name": name, "args": args})
            reply = {
                "ok": True,
                "output": answer,
                "raw_output": {
                    "answer": answer,
                    "question": question,
                    "tool_calls": tool_calls,
                    "workbook": graph_module.workbook_path(),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
