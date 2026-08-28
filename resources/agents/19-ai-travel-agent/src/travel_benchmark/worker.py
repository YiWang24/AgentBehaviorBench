"""JSONL worker for the travel agent.

The graph is compiled with ``interrupt_before=['email_sender']``, which is
upstream's own approval gate: the plan is produced, and a human decides whether
to send it. The benchmark honours that gate and never resumes past it, so no
email is ever sent. The answer under test is the itinerary the agent produced
when it stopped asking for tools.
"""

from __future__ import annotations

import contextlib
import json
import sys
import uuid


def _request_text(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("question", "query", "prompt", "input", "text", "content", "request"):
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
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "\n".join(part for part in parts if part)
    return content if isinstance(content, str) else ""


def _tool_calls(messages: list) -> list[dict]:
    calls = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
            calls.append({"name": name, "args": args})
    return calls


def main() -> int:
    from langchain_core.messages import HumanMessage

    from . import graph as graph_module

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
            request = _request_text(payload)
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}
            # Every print inside the graph goes to stderr; stdout is the protocol.
            with contextlib.redirect_stdout(sys.stderr):
                state = compiled.invoke({"messages": [HumanMessage(content=request)]}, config=config)

            messages = state.get("messages") or []
            answer = ""
            for message in reversed(messages):
                body = _text(message).strip()
                if body:
                    answer = body
                    break

            reply = {
                "ok": True,
                "output": answer,
                "raw_output": {
                    "itinerary": answer,
                    "request": request,
                    "tool_calls": _tool_calls(messages),
                    "email_sent": False,
                    "stopped_at": "email_sender approval gate",
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
