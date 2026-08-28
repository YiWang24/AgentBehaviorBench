"""Benchmark guard for the MCP agent.

Both MCP servers are local stdio subprocesses shipped with the project: one
reports the system clock, the other returns a fixed weather string that
upstream itself documents as a mock. Neither reaches the network, so nothing is
substituted and this installs the egress guard only — a revision that adds a
server calling a real API fails loudly rather than silently.
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
