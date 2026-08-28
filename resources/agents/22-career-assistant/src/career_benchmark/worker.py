"""JSONL worker for the career assistant."""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import sys


def _request(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("user_input", "question", "query", "prompt", "input", "text", "content"):
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
    pathlib.Path(os.environ.setdefault("CAREER_WORKSPACE", "/tmp/career")).mkdir(
        parents=True, exist_ok=True
    )

    from langchain_core.messages import HumanMessage

    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    model = os.environ.get("CAREER_MODEL", "gpt-4o")
    limit = int(os.environ.get("CAREER_RECURSION_LIMIT", "30"))

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
            callback = graph_module.BenchmarkCallback()
            with contextlib.redirect_stdout(sys.stderr):
                state = compiled.invoke(
                    {
                        "user_input": request,
                        "messages": [HumanMessage(content=request)],
                        "next_step": "",
                        # Upstream builds the model from the state, not the
                        # environment: init_chat_model(**state["config"]).
                        "config": {"model": model, "model_provider": "openai"},
                        "callback": callback,
                    },
                    config={"recursion_limit": limit},
                )

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
                    "answer": answer,
                    "request": request,
                    "agents_used": callback.agent_names,
                    "transcript": [
                        {"name": getattr(m, "name", None), "content": _text(m)}
                        for m in messages
                    ],
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
