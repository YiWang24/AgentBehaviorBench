"""Wire the deterministic fixtures into the web researcher.

Both tools build their client inside the call, so replacing the names they look
up is enough and the tool functions themselves run unchanged. Replacing the
Selenium loader also means the image needs no browser or chromedriver.
"""

from __future__ import annotations

from . import corpus
from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


class BenchmarkSearchResults:
    """Offline stand-in for ``DuckDuckGoSearchResults``."""

    def invoke(self, query, **kwargs) -> str:
        text = query if isinstance(query, str) else str((query or {}).get("query", ""))
        found = corpus.search_results(text, 4)
        return ", ".join(
            f"snippet: {item['content']}, title: {item['title']}, link: {item['url']}"
            for item in found["results"]
        )


class BenchmarkDocument:
    """Minimal stand-in for a LangChain Document."""

    def __init__(self, page_content: str, metadata: dict) -> None:
        self.page_content = page_content
        self.metadata = metadata

    def __repr__(self) -> str:
        return f"Document(page_content={self.page_content[:60]!r})"


class BenchmarkURLLoader:
    """Offline stand-in for ``SeleniumURLLoader``; no browser is involved."""

    def __init__(self, urls, **kwargs) -> None:
        self.urls = list(urls or [])

    def load(self) -> list[BenchmarkDocument]:
        return [
            BenchmarkDocument(corpus.page_markdown(url), {"source": str(url)})
            for url in self.urls
        ] or [BenchmarkDocument("", {"source": ""})]


def _patch_tools() -> None:
    from tools import duck_duck_go_web_search, fetch_web_page_content

    duck_duck_go_web_search.DuckDuckGoSearchResults = BenchmarkSearchResults
    fetch_web_page_content.SeleniumURLLoader = BenchmarkURLLoader


def install() -> None:
    """Install every mock. Idempotent."""
    global _installed
    if _installed:
        return

    _patch_tools()
    install_network_guard()
    _installed = True
