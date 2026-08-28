"""Wire the deterministic fixtures into the deep-research example.

The example reaches exactly two services: Tavily for URL discovery and an
``httpx.get`` page fetch. Both live in ``research_agent.tools`` as module
globals, so replacing the attributes leaves the tool's own formatting logic —
which is the part the benchmark should exercise — completely intact.
"""

from __future__ import annotations

from . import corpus
from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


class BenchmarkTavilyClient:
    """Offline stand-in for ``tavily.TavilyClient``."""

    def search(self, query: str, max_results: int = 1, topic: str = "general", **kwargs):
        return corpus.search_results(query, max_results, topic)


def _patch_research_tools() -> None:
    # Importing the module constructs TavilyClient() at module level, so the
    # placeholder key set by the runtime boundary must already be in place.
    from research_agent import tools

    tools.tavily_client = BenchmarkTavilyClient()
    tools.fetch_webpage_content = lambda url, timeout=10.0: corpus.page_markdown(url)


def install() -> None:
    """Install every mock. Idempotent."""
    global _installed
    if _installed:
        return

    _patch_research_tools()
    install_network_guard()

    _installed = True
