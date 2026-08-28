"""Install the benchmark boundary for the langtalks SWE agent."""

from __future__ import annotations

from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


def install() -> None:
    """Block non-model egress. Idempotent.

    The agent's tools are filesystem tools; the only network client reachable
    from them is ``gitingest``, and it is only ever handed a local directory.
    Blocking the HTTP clients turns any accidental remote fetch into a loud
    failure rather than a silent one.
    """
    global _installed
    if _installed:
        return

    install_network_guard()
    _installed = True
