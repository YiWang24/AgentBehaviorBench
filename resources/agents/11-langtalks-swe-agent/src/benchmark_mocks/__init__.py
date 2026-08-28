"""Benchmark boundary for the langtalks SWE agent.

This agent's work is filesystem work, so instead of stubbing its tools the
benchmark gives it a real deterministic project to edit inside a writable
tmpfs workspace. Network access is blocked: the agent has no legitimate
non-model egress.
"""

from __future__ import annotations

from .install import install, installed
from .workspace import materialise, reset_trace, snapshot, trace_summary

__all__ = [
    "install",
    "installed",
    "materialise",
    "reset_trace",
    "snapshot",
    "trace_summary",
]
