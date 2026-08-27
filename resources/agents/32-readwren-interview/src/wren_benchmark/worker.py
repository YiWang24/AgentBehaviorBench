"""JSONL worker for the literary interview agent.

Each invocation is one interview turn: the graph analyses the conversation so
far and either asks the next question or, once it judges the interview complete,
generates the reading profile. The Case's text is the interviewee's latest
answer; a follow-up run continues the same thread.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import uuid


def _answer(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("answer", "response", "message", "question", "query", "prompt", "input", "text", "content"):
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
            answer = _answer(payload)
            with contextlib.redirect_stdout(sys.stderr):
                state = compiled.invoke(
                    {
                        "messages": [HumanMessage(content=answer)],
                        "turn_count": 0,
                        "profile_data": {},
                        "is_complete": False,
                        "current_analysis": {},
                    },
                    config={"configurable": {"thread_id": str(uuid.uuid4())}},
                )
            messages = state.get("messages") or []
            reply_text = ""
            for message in reversed(messages):
                body = _text(message).strip()
                if body:
                    reply_text = body
                    break
            reply = {
                "ok": True,
                "output": reply_text,
                "raw_output": {
                    "reply": reply_text,
                    "answer": answer,
                    "turn_count": state.get("turn_count"),
                    "is_complete": state.get("is_complete"),
                    "profile_data": state.get("profile_data"),
                    "analysis": state.get("current_analysis"),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
