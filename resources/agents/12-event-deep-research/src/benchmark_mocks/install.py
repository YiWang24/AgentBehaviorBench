"""Wire the deterministic fixtures into the event research pipeline.

Three things reach outside the process: Tavily for URL discovery, an aiohttp
crawler that fetches those URLs, and the Langfuse callback handler. All three
are replaced before the graphs are imported.
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
        self.exclude_domains = kwargs.get("exclude_domains") or []

    def _payload(self, query: str) -> dict:
        found = corpus.search_results(query, self.max_results)
        return {
            "query": query,
            "results": [
                {
                    "title": item["title"],
                    "url": item["url"],
                    "content": item["content"],
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
    from src.research_events import research_events_graph

    research_events_graph.TavilySearch = BenchmarkTavilySearch


def _patch_crawler() -> None:
    """Replace the Firecrawl page fetch with deterministic markdown.

    `url_crawl` calls `scrape_page_content`, which POSTs to the Firecrawl API
    and swallows every exception into `None`. Left alone it would quietly
    return empty content for every page under the egress guard, so the agent
    would appear to work while researching nothing.
    """
    from src.url_crawler import utils as crawler_utils

    async def _scrape(url, *args, **kwargs):
        return corpus.page_markdown(url)

    crawler_utils.scrape_page_content = _scrape


def _patch_reasoning_flag() -> None:
    """Drop a provider-specific kwarg that no supported provider accepts.

    `llm_service` pins `reasoning: "False"` on every model it builds. Google
    tolerates it, but ChatOpenAI rejects the string during validation and
    Anthropic rejects it at call time with
    `AsyncMessages.create() got an unexpected keyword argument 'reasoning'`.
    That ties upstream to Gemini in practice even though the model field is
    configurable, and the Interceptor cannot capture Gemini.

    The value is `"False"` -- reasoning is switched off -- so removing it when
    it is not a real dict changes no model behaviour. A genuine reasoning
    config is left alone.
    """
    from src import llm_service

    original = llm_service._build_and_configure_model

    def _build(config, model_chain, model_name, max_tokens, max_retries):
        runnable = original(config, model_chain, model_name, max_tokens, max_retries)
        applied = getattr(runnable, "config", None) or {}
        if isinstance(applied, dict) and not isinstance(applied.get("reasoning"), dict):
            applied.pop("reasoning", None)
        return runnable

    llm_service._build_and_configure_model = _build


def _patch_tracing() -> None:
    """Langfuse would ship traces to a hosted service; the benchmark has no egress.

    The handler cannot simply be dropped: `src/graph.py` puts the return value
    straight into a callbacks list at import time, and LangChain then calls
    `run_inline` on it. Upstream returns None only when langfuse is absent, so
    that path is never exercised there. An inert BaseCallbackHandler satisfies
    the interface and records nothing.
    """
    from langchain_core.callbacks import BaseCallbackHandler

    from src import utils

    utils.get_langfuse_handler = lambda: BaseCallbackHandler()


def install() -> None:
    """Install every mock. Idempotent."""
    global _installed
    if _installed:
        return

    _patch_tracing()
    _patch_reasoning_flag()
    _patch_search()
    _patch_crawler()
    install_network_guard()

    _installed = True
