"""JSONL worker for the deep research agent."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import uuid


def _topic(payload: dict) -> str:
    value = payload.get("input", payload)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("research_topic", "topic", "question", "query", "prompt", "input", "text", "content"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found
        messages = value.get("messages")
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict) and isinstance(last.get("content"), str):
                return last["content"]
    return json.dumps(value, ensure_ascii=False)


def _final(state) -> str:
    getter = state.get if isinstance(state, dict) else lambda k, d=None: getattr(state, k, d)
    report = getter("final_report") or getter("report")
    if isinstance(report, str) and report.strip():
        return report
    sections = getter("report_sections") or []
    parts = []
    for section in sections:
        title = getattr(section, "title", None) or (section.get("title") if isinstance(section, dict) else None)
        content = getattr(section, "content", None) or (section.get("content") if isinstance(section, dict) else None)
        if content:
            parts.append(f"## {title}\n\n{content}" if title else content)
    if parts:
        return "\n\n".join(parts)
    return str(getter("error") or "")


def main() -> int:
    from . import graph as graph_module

    with contextlib.redirect_stdout(sys.stderr):
        compiled = graph_module.graph()

    limit = int(os.environ.get("DR_RECURSION_LIMIT", "40"))

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
            topic = _topic(payload)
            with contextlib.redirect_stdout(sys.stderr):
                # The nodes are async-only; compiled.invoke() raises.
                state = asyncio.run(compiled.ainvoke(
                    {"research_topic": topic},
                    config={"recursion_limit": limit,
                            "configurable": {"thread_id": str(uuid.uuid4())}},
                ))
            getter = state.get if isinstance(state, dict) else lambda k, d=None: getattr(state, k, d)
            report = _final(state)
            reply = {
                "ok": True,
                "output": report,
                "raw_output": {
                    "report": report,
                    "research_topic": topic,
                    "plan": str(getter("plan") or ""),
                    "key_findings": getter("key_findings"),
                    "num_sources": len(getter("search_results") or []),
                    "error": getter("error"),
                },
            }
        except Exception as exc:  # noqa: BLE001 - reported to the harness
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        print(json.dumps(reply, ensure_ascii=False, default=str), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
