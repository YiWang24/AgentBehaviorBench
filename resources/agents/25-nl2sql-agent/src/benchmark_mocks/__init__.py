"""Benchmark guard for the NL2SQL agent.

The datasource is a local SQLite file and the only outbound dependency is the
model provider, so nothing is substituted — this installs the egress guard
only. A revision that reaches for Databricks, Cosmos, or Azure Sessions fails
loudly rather than silently.
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
