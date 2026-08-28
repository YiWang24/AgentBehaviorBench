"""LangGraph entry point for the benchmark adaptation of the AgentK web researcher.

The upstream graph is imported unchanged: a reasoning node bound to a web-search
tool and a page-fetch tool, looping through a tool node until it stops calling
tools.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from agents.web_researcher import graph as _graph, system_prompt  # noqa: E402

RECURSION_LIMIT = 30


def graph():
    """Zero-argument factory returning the compiled web researcher."""
    return _graph


def _text_of(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(block.get("text", ""))
            if isinstance(block, dict) and block.get("type") == "text"
            else block
            if isinstance(block, str)
            else ""
            for block in content
        ]
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


async def run_research(task: str, run_config: dict | None = None) -> dict[str, Any]:
    """Research one task and normalize the public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)

    state = await _graph.ainvoke(
        {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
        },
        config=config,
    )

    messages = state.get("messages") or []
    tool_calls: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                tool_calls.append(str(name))

    return {
        "task": task,
        "answer": _text_of(messages[-1]) if messages else "",
        "tool_calls": tool_calls,
        "message_count": len(messages),
    }
