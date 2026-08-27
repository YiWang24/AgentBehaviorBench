"""Expose the research graph with search and scraping replaced by fixtures.

`MODEL_PROVIDER` defaults to gemini upstream, whose native protocol the Model
Interceptor cannot capture. The manifest sets it to `openai`, so the plain
`ChatOpenAI` path is taken. The stand-ins must be installed before
`src.utils.tools` is imported (it builds the search providers at import time),
which is why `create_research_graph` is imported lazily inside `graph()`.
"""

from __future__ import annotations

import benchmark_mocks

_compiled = None


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install()
        from src.graph import create_memory_checkpointer, create_research_graph

        _compiled = create_research_graph(checkpointer=create_memory_checkpointer())
    return _compiled
