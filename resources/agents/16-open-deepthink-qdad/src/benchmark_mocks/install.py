"""Benchmark boundary for the QDAD graph.

The selected graph is self-contained: its five nodes reason over a language
grid and reach nothing but the chat model — no search, no retrieval, no
filesystem. There is therefore nothing to substitute, and this module only
installs the egress guard so that any dependency reaching for the network in a
future revision fails loudly rather than silently.
"""

from __future__ import annotations

from .network_guard import install as install_network_guard

_installed = False
TRACE: list[dict[str, object]] = []


def installed() -> bool:
    return _installed


def trace_summary() -> list[dict[str, object]]:
    return [dict(entry) for entry in TRACE]


def reset_trace() -> None:
    TRACE.clear()


def install() -> None:
    """Install the boundary. Idempotent."""
    global _installed
    if _installed:
        return

    install_network_guard()
    _installed = True
