"""Benchmark guard for the patent-drafting workflow.

The drafting graph calls the model and reaches nothing else — Chroma lives in
`tools/`, off the graph path, and is not vendored. Nothing is substituted, so
this installs the egress guard only: a revision that reaches for the vector
store fails loudly rather than silently.
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
