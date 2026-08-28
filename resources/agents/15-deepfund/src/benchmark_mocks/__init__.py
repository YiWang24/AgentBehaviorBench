"""Deterministic stand-ins for every non-LLM service DeepFund uses.

The model provider is the only permitted real dependency. All market data comes
from local fixtures built from DeepFund's own typed models, and anything else
that reaches the network raises.
"""

from __future__ import annotations

from .install import BenchmarkRouter, install, installed
from .market import reset_trace, trace_summary

__all__ = ["BenchmarkRouter", "install", "installed", "reset_trace", "trace_summary"]
