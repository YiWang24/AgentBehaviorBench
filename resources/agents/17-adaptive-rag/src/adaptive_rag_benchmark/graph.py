"""LangGraph entry point for the benchmark adaptation of Adaptive RAG.

The upstream graph is imported unchanged: a query classifier routes between
retrieval, web search, and a direct answer; retrieved documents are graded and
the query rewritten when they are not relevant.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from src.rag.graph_builder import builder as _graph  # noqa: E402

RECURSION_LIMIT = 30


def graph():
    """Zero-argument factory returning the compiled Adaptive RAG graph."""
    return _graph


def _text_of(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return "" if content is None else str(content)


async def run_query(question: str, run_config: dict | None = None) -> dict[str, Any]:
    """Answer one question and normalize the public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)

    state = await _graph.ainvoke(
        {"messages": [{"role": "user", "content": question}], "latest_query": question},
        config=config,
    )

    messages = state.get("messages") or []
    return {
        "question": question,
        "answer": _text_of(messages[-1]) if messages else "",
        "message_count": len(messages),
        "indexed_documents": [name for name, _ in benchmark_mocks.DOCUMENTS],
    }
