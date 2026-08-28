"""Deterministic stand-ins for every non-LLM service the research agent uses.

The model provider is the only permitted real dependency. Web search and page
fetching resolve locally, and anything left over raises.

``install()`` is idempotent and must run before ``research_agent.agent`` is
imported.
"""

from __future__ import annotations

from .install import BenchmarkTavilyClient, install, installed

__all__ = ["BenchmarkTavilyClient", "install", "installed"]
