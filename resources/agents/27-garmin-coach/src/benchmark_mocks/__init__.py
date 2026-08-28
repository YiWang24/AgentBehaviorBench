"""Benchmark guard for the training coach.

The analysis workflow reads its data from graph state, so the Garmin client is
never reached on this path and nothing needs substituting. This installs the
egress guard only: a revision that reaches for Garmin Connect, the Outside API,
or LangSmith fails loudly rather than silently.
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
