"""Wire the deterministic fixtures into upstream gpt-researcher.

Three substitutions cover the whole non-LLM surface:

* the retriever, declared with ``requires_scraping = False`` so the pipeline
  never reaches the scraper layer at all;
* embeddings, which have no interceptor route and must not escape;
* a guard that turns any remaining egress into a loud failure.
"""

from __future__ import annotations

import sys

from . import corpus
from .embeddings import BENCHMARK_EMBEDDINGS
from .network_guard import install as install_network_guard

RETRIEVER_NAME = "benchmark"

_installed = False


def installed() -> bool:
    return _installed


class BenchmarkRetriever:
    """Offline stand-in for Tavily, Exa, DuckDuckGo, and friends.

    ``requires_scraping = False`` tells the pipeline that each result already
    carries its content, which removes the scraper — and therefore the whole
    browser and HTTP-fetch surface — from the run.
    """

    requires_scraping = False

    def __init__(self, query: str, query_domains=None, headers=None, **kwargs):
        self.query = query
        self.query_domains = query_domains

    def search(self, max_results: int = 5) -> list[dict[str, str]]:
        corpus.record("web-search", "search", f"{str(self.query)[:80]!r} -> {max_results}")
        return corpus.documents(self.query, max_results)


def _patch_retrievers() -> None:
    from gpt_researcher.actions import retriever as retriever_module

    def _get_retriever(name: str):
        return BenchmarkRetriever

    def _get_retrievers(headers, cfg):
        return [BenchmarkRetriever]

    retriever_module.get_retriever = _get_retriever
    retriever_module.get_retrievers = _get_retrievers

    # Consumers bind these by name at import time.
    for module_name in ("gpt_researcher.actions", "gpt_researcher.agent"):
        module = sys.modules.get(module_name)
        if module is not None:
            if hasattr(module, "get_retriever"):
                module.get_retriever = _get_retriever
            if hasattr(module, "get_retrievers"):
                module.get_retrievers = _get_retrievers


def _patch_retriever_validation() -> None:
    """Accept the benchmark retriever without importing the retriever package.

    ``Config.parse_retrievers`` validates the configured name against
    ``get_all_retriever_names()``, which eagerly imports every retriever module
    — arxiv, exa_py, tavily, ddgs, firecrawl, and the rest. All of them are
    mocked, so installing those clients only to satisfy a name check would add
    a large unused dependency surface to the image.
    """
    from gpt_researcher.config.config import Config

    def _parse_retrievers(self, retriever_str: str) -> list[str]:
        names = [name.strip() for name in str(retriever_str or "").split(",") if name.strip()]
        return [RETRIEVER_NAME] if not names else [RETRIEVER_NAME for _ in names]

    Config.parse_retrievers = _parse_retrievers


def _patch_embeddings() -> None:
    from gpt_researcher.memory import embeddings as embeddings_module

    def _get_embeddings(self):
        corpus.record("embeddings", "get_embeddings", "deterministic local vectors")
        return BENCHMARK_EMBEDDINGS

    def _init(self, embedding_provider=None, model=None, **kwargs):
        self._embeddings = BENCHMARK_EMBEDDINGS

    embeddings_module.Memory.__init__ = _init
    embeddings_module.Memory.get_embeddings = _get_embeddings


def install() -> None:
    """Install every mock. Idempotent."""
    global _installed
    if _installed:
        return

    _patch_retrievers()
    _patch_retriever_validation()
    _patch_embeddings()
    install_network_guard()

    _installed = True
