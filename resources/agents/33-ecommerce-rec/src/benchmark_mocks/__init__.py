"""Benchmark guard for the e-commerce recommendation pipeline.

The catalogue is already a fixture (`MOCK_PRODUCTS`), the feature store degrades
to empty features without a Redis client, and Milvus / SQLAlchemy are not on
the graph path. Only the model is reached, so nothing is substituted and this
installs the egress guard only — a revision that connects to Redis, Milvus or a
database fails loudly rather than silently.
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
