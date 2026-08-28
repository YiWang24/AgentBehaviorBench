"""Benchmark guard for the ETF rotation agent.

The three nodes compute metrics from the price series in graph state and call
the model; nothing else is reached. Nothing is substituted, so this installs
the egress guard only — a revision that reaches for the market-data or news
APIs fails loudly rather than silently.
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
