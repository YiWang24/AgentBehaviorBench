"""Benchmark guard for the Excel agent.

Every tool reads the loaded workbook through pandas; nothing but the model is
reached over the network. Nothing is substituted, so this installs the egress
guard only — a future revision that reaches for an embeddings service or the
knowledge base fails loudly rather than silently.
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
