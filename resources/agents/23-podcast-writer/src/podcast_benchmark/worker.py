"""JSONL worker for the podcast writer."""

from __future__ import annotations

import contextlib
import json
import sys


def _source_text(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("main_text", "text", "document", "article", "content", "prompt", "input", "query", "question"):
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
    if isinstance(content, str):
        return content
    return message if isinstance(message, str) else ""


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
            source = _source_text(payload)
            with contextlib.redirect_stdout(sys.stderr):
                state = compiled.invoke({"main_text": HumanMessage(content=source)})
            script = _text(state.get("enhanced_script"))
            reply = {
                "ok": True,
                "output": script,
                "raw_output": {
                    "enhanced_script": script,
                    "script_essence": _text(state.get("script_essence")),
                    "key_points": _text(state.get("key_points")),
                    "source_text": source,
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
