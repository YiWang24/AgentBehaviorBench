"""Deterministic stand-ins for every non-LLM service TradingAgents talks to.

The benchmark allows exactly one real network dependency: the model provider.
Market data, fundamentals, news, macro series, prediction markets, and symbol
identity lookups must all resolve locally and identically on every run, and a
gap in mock coverage has to fail loudly instead of silently reaching Yahoo,
Alpha Vantage, FRED, or Polymarket.

``install()`` is idempotent and must run *before* ``tradingagents.graph`` is
imported, because several upstream modules bind these callables by name at
import time.
"""

from __future__ import annotations

from .install import install, installed

__all__ = ["install", "installed"]
