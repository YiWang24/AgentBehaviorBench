"""Wire the deterministic fixtures into the ReAct agent.

The agent reaches exactly one external service: Tavily, constructed per call
inside ``react_agent.tools.search``. Replacing the module-level ``TavilySearch``
name is therefore enough, and it leaves the ``search`` tool itself — the part
the benchmark measures — running unchanged.
"""

from __future__ import annotations

from . import corpus
from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


class BenchmarkTavilySearch:
    """Offline stand-in for ``langchain_tavily.TavilySearch``."""

    def __init__(self, max_results: int = 5, **kwargs: object) -> None:
        self.max_results = max_results

    def _payload(self, query: str) -> dict:
        found = corpus.search_results(query, self.max_results)
        return {
            "query": query,
            "results": [
                {
                    "title": item["title"],
                    "url": item["url"],
                    "content": corpus.page_markdown(item["url"]),
                    "score": item["score"],
                }
                for item in found["results"]
            ],
            "response_time": 0.01,
        }

    def invoke(self, payload, **kwargs):
        return self._payload(str((payload or {}).get("query", "")))

    async def ainvoke(self, payload, **kwargs):
        return self._payload(str((payload or {}).get("query", "")))


def _patch_search() -> None:
    from react_agent import tools

    tools.TavilySearch = BenchmarkTavilySearch


def install() -> None:
    """Install every mock. Idempotent."""
    global _installed
    if _installed:
        return

    _patch_search()
    install_network_guard()

    _installed = True
