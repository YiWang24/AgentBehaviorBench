"""Replace the search and content-extraction layer.

`src/utils/web_utils.py` builds `DuckDuckGoProvider`, `TavilyProvider` and
`ContentExtractor`, all instantiated at import time by `src/utils/tools.py`.
Rather than swap the classes wholesale, the two methods that actually reach the
network — `DuckDuckGoProvider._execute_search` and
`ContentExtractor.extract_content_async` — are replaced on the classes, so the
retry, rate-limit and circuit-breaker wrappers around them (and the
`SearchResult` shape they return) are exercised unchanged.

This runs before `src.utils.tools` is imported, so the providers those classes
back are already fixture-backed when the tools are built.
"""

from __future__ import annotations

from . import fixtures
from .network_guard import install as install_network_guard

_installed = False


def install() -> None:
    global _installed
    if _installed:
        return

    from src.state import SearchResult
    from src.utils import web_utils

    async def _execute_search(self, query, max_results):
        return [
            SearchResult(
                query=query,
                title=result["title"],
                url=result["url"],
                snippet=result["snippet"],
            )
            for result in fixtures.results_for(query, max_results)
        ]

    async def _extract_content_async(self, url):
        return fixtures.body_for(url)

    web_utils.DuckDuckGoProvider._execute_search = _execute_search
    web_utils.ContentExtractor.extract_content_async = _extract_content_async

    # Tavily is not used (search_provider defaults to duckduckgo), but guard it
    # too in case a Case flips the provider.
    async def _tavily_search(self, query, max_results=None):
        return [
            SearchResult(query=query, title=r["title"], url=r["url"], snippet=r["snippet"])
            for r in fixtures.results_for(query, max_results or self.max_results)
        ]

    web_utils.TavilyProvider.search = _tavily_search

    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
