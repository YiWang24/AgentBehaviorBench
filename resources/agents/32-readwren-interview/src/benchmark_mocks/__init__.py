"""Benchmark guard for the literary interview agent.

The three nodes reason over the conversation and call the model; the only other
dependency is Redis, used purely for checkpoint persistence and configured off
here (`use_redis=False`), so nothing is substituted. This installs the egress
guard only — a revision that reaches for a real service fails loudly rather
than silently.
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
