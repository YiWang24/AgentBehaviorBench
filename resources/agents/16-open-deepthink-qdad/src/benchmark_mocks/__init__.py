"""Benchmark boundary for open-deepthink's QDAD graph.

The model provider is the only dependency the selected graph has. Everything
else that reaches the network raises.
"""

from __future__ import annotations

from .install import install, installed, reset_trace, trace_summary

__all__ = ["install", "installed", "reset_trace", "trace_summary"]
