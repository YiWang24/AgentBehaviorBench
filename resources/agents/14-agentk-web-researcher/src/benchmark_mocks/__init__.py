"""Deterministic stand-ins for the web researcher's non-model dependencies.

The model provider is the only permitted real dependency. Search and page
fetching resolve from a local corpus, and anything else that reaches the
network raises.
"""

from __future__ import annotations

from .corpus import reset_trace, trace_summary
from .install import install, installed

__all__ = ["install", "installed", "reset_trace", "trace_summary"]
