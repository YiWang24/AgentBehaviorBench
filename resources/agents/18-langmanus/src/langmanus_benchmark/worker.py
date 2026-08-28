"""JSONL worker for the LangManus workflow.

Reads one request per line on stdin, writes one reply per line on stdout.
Nothing else may reach stdout, so the graph's own logging is sent to stderr.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import sys


def _prepare_workspace() -> None:
    """Give the coder and file tools somewhere writable.

    The container root is read-only and ``/tmp`` is the only writable mount, so
    the process runs there. Upstream writes relative to the working directory.
    """
    root = pathlib.Path(os.environ.get("LANGMANUS_WORKSPACE", "/tmp/langmanus"))
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)


def _question(payload: dict) -> str:
    """Accept the Case's text under any of the keys a provider might use."""
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
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "\n".join(part for part in parts if part)
    return content if isinstance(content, str) else ""


def _final_answer(state: dict) -> str:
    """The reporter's message if it ran, else the last non-empty message."""
    messages = state.get("messages") or []
    for message in reversed(messages):
        name = getattr(message, "name", None) or (
            message.get("name") if isinstance(message, dict) else None
        )
        if name == "reporter" and _text(message).strip():
            return _text(message)
    for message in reversed(messages):
        body = _text(message).strip()
        if body:
            return body
    return ""


def main() -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    _prepare_workspace()

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
            question = _question(payload)
            state = compiled.invoke(
                graph_module.initial_state(question),
                config={"recursion_limit": int(os.environ.get("LANGMANUS_RECURSION_LIMIT", "40"))},
            )
            answer = _final_answer(state)
            reply = {
                "ok": True,
                "output": answer,
                "raw_output": {
                    "answer": answer,
                    "question": question,
                    "next": state.get("next"),
                    "full_plan": state.get("full_plan"),
                    "messages": [
                        {
                            "name": getattr(m, "name", None)
                            or (m.get("name") if isinstance(m, dict) else None),
                            "content": _text(m),
                        }
                        for m in (state.get("messages") or [])
                    ],
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
