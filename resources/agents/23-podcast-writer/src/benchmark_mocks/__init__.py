"""Benchmark guard for the podcast writer.

The three nodes reason over the text they are given and reach nothing but the
model — no search, no retrieval, no filesystem. Nothing is substituted, so this
installs the egress guard only: a future revision that reaches for the network
fails loudly rather than silently.
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
