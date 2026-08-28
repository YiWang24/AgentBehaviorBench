"""LangGraph entry point for the benchmark adaptation of the ReAct agent.

The upstream graph is imported unchanged: the same call_model / tools loop with
its original prompt and context. Only the search backend is replaced.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from react_agent.context import Context  # noqa: E402
from react_agent.graph import graph as _graph  # noqa: E402

RECURSION_LIMIT = 30


def graph():
    """Zero-argument factory returning the compiled ReAct agent."""
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


async def run_agent(query: str, run_config: dict | None = None) -> dict[str, Any]:
    """Run the agent for one query and normalize its public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)

    # The graph declares `context_schema=Context`, so the caller supplies the
    # runtime context; upstream's dev server does the same. Context reads its
    # defaults from environment variables pinned by the runtime boundary.
    state = await _graph.ainvoke(
        {"messages": [{"role": "user", "content": query}]},
        config=config,
        context=Context(),
    )

    messages = state.get("messages") or []
    tool_calls: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                tool_calls.append(str(name))

    return {
        "query": query,
        "answer": _text_of(messages[-1]) if messages else "",
        "tool_calls": tool_calls,
        "message_count": len(messages),
    }
