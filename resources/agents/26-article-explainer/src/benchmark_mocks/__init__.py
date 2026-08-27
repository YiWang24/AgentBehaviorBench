"""Benchmark guard for the article explainer.

The five agents hand off to one another and reach nothing but the model — no
search, no retrieval, no filesystem on the graph path. Nothing is substituted,
so this installs the egress guard only: a revision that reaches for a local
Ollama endpoint or the network fails loudly rather than silently.
"""

from .network_guard import install

_installed = False


def install_all() -> None:
    global _installed
    if _installed:
        return
    install()
    _installed = True


def installed() -> bool:
    return _installed


__all__ = ["install_all", "installed"]
