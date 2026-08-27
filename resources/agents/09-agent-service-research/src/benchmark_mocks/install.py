"""Wire the deterministic fixtures into the research assistant.

The selected graph reaches exactly one external service: DuckDuckGo, through
``DuckDuckGoSearchResults``. Its API wrapper is replaced so the tool object the
graph already bound keeps running — its own result formatting is exercised by
the benchmark rather than stubbed out.
"""

from __future__ import annotations

from . import corpus
from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


class BenchmarkSearchWrapper:
    """Offline stand-in for ``DuckDuckGoSearchAPIWrapper``."""

    def __init__(self, max_results: int = 4) -> None:
        self.max_results = max_results

    def results(self, query: str, max_results: int | None = None, source: str | None = None):
        return corpus.results(query, max_results or self.max_results)

    def run(self, query: str) -> str:
        return "\n\n".join(item["snippet"] for item in self.results(query))


def _patch_search(tools) -> None:
    """Swap the API wrapper on every DuckDuckGo tool the graph bound."""
    for tool in tools:
        wrapper = getattr(tool, "api_wrapper", None)
        if wrapper is not None and type(wrapper).__name__.startswith("DuckDuckGo"):
            object.__setattr__(tool, "api_wrapper", BenchmarkSearchWrapper())
            corpus.record("web-search", "patched", type(tool).__name__)


def install() -> None:
    """Install every mock. Idempotent.

    Must run after ``agents.research_assistant`` is imported, because the tool
    objects are constructed at module import time and bound into the graph.
    """
    global _installed
    if _installed:
        return

    from agents import research_assistant as module

    _patch_search(module.tools)
    install_network_guard()

    _installed = True
