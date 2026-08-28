"""Deterministic stand-ins for every non-LLM service gpt-researcher talks to.

The model provider is the only permitted real dependency. Web search,
scraping, and embeddings all resolve locally, and anything left over raises.

``install()`` is idempotent and must run before the research graph is built.
"""

from __future__ import annotations

from .install import RETRIEVER_NAME, BenchmarkRetriever, install, installed

__all__ = ["RETRIEVER_NAME", "BenchmarkRetriever", "install", "installed"]
