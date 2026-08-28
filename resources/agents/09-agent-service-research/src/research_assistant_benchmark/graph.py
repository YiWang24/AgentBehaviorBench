"""LangGraph entry point for the benchmark adaptation of the research assistant.

The upstream graph is imported unchanged: safeguard, model, and tool nodes with
their original prompts, tools, and routing. Only the search API wrapper is
replaced, and only after the module has constructed its tools.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

from agents.research_assistant import research_assistant  # noqa: E402

import benchmark_mocks  # noqa: E402  (patches tools the module just built)

benchmark_mocks.install()

RECURSION_LIMIT = 30


def graph():
    """Zero-argument factory returning the compiled research assistant."""
    return research_assistant


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


async def run_research(query: str, run_config: dict | None = None) -> dict[str, Any]:
    """Run the assistant for one query and normalize its public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)
    config.setdefault("configurable", {})

    state = await research_assistant.ainvoke(
        {"messages": [{"role": "user", "content": query}]}, config=config
    )

    messages = state.get("messages") or []
    tool_calls: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                tool_calls.append(str(name))

    safety = state.get("safety")
    return {
        "query": query,
        "answer": _text_of(messages[-1]) if messages else "",
        "safety_assessment": getattr(
            getattr(safety, "safety_assessment", None), "value", None
        ),
        "tool_calls": tool_calls,
        "message_count": len(messages),
    }
