"""Deterministic stand-ins for every non-LLM service the event researcher uses.

The model provider is the only permitted real dependency. Search and page
fetching resolve from a local corpus, tracing is disabled, and anything left
over raises.
"""

from __future__ import annotations

from .install import BenchmarkTavilySearch, install, installed

__all__ = ["BenchmarkTavilySearch", "install", "installed"]
