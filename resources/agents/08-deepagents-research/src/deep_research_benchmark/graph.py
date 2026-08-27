"""LangGraph entry point for the benchmark adaptation of the deep-research example.

The upstream agent is imported unchanged: same prompts, same tools, same
sub-agent delegation, same model client. Only the two network-backed tool
helpers are replaced, and only before the agent module is imported.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from research_agent.agent import agent as _agent  # noqa: E402

RECURSION_LIMIT = 60


def graph():
    """Zero-argument factory returning the compiled deep-research agent."""
    return _agent


def _text_of(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(part for part in parts if part)
    return "" if content is None else str(content)


def run_research(query: str, run_config: dict | None = None) -> dict[str, Any]:
    """Run the agent for one query and normalize its public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)

    state = _agent.invoke({"messages": [{"role": "user", "content": query}]}, config=config)

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
        "files": sorted(state.get("files") or {}),
    }
