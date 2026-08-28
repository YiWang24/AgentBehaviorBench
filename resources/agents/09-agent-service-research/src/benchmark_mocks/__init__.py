"""Deterministic stand-ins for every non-LLM service the research assistant uses.

The model provider is the only permitted real dependency. Web search resolves
from a local corpus, and anything left over raises.
"""

from __future__ import annotations

from .install import BenchmarkSearchWrapper, install, installed

__all__ = ["BenchmarkSearchWrapper", "install", "installed"]
