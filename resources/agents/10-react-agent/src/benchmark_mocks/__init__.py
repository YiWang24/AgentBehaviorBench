"""Deterministic stand-ins for every non-LLM service the ReAct agent uses.

The model provider is the only permitted real dependency. Web search resolves
from a local corpus, and anything left over raises.
"""

from __future__ import annotations

from .install import BenchmarkTavilySearch, install, installed

__all__ = ["BenchmarkTavilySearch", "install", "installed"]
