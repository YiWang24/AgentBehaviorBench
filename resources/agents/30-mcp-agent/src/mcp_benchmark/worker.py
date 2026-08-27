"""JSONL worker for the MCP-backed ReAct agent.

The MCP client and its subprocesses are started once and reused, so the
per-request cost is the agent loop rather than two process spawns.
"""

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


def _text(message: object) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


async def _run() -> int:
    from langchain_core.messages import HumanMessage

    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        agent = await graph_module.build()

    limit = int(os.environ.get("MCP_RECURSION_LIMIT", "25"))
    loop = asyncio.get_running_loop()

    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
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
                state = await agent.ainvoke(
                    {"messages": [HumanMessage(content=question)]},
                    config={
                        "recursion_limit": limit,
                        "configurable": {"thread_id": str(uuid.uuid4())},
                    },
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
                    "mcp_servers": sorted(graph_module.mcp_config()),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
