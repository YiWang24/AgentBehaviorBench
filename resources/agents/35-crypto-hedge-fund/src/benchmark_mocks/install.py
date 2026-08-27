"""Replace Binance data access with deterministic fixture klines.

`src/graph/data_node.py` builds one `BinanceDataProvider()` at module scope and
calls `get_history_klines_with_end_time`. That method (and its siblings) are the
only things that reach the exchange, so they are replaced on the class before
the graph is built. The provider's constructor still runs, but it creates no
network connection until a fetch is attempted, and none now is.
"""

from __future__ import annotations

from datetime import datetime

from . import klines as klines_module
from .network_guard import install as install_network_guard

_installed = False


def install() -> None:
    global _installed
    if _installed:
        return

    # Everything in this project is importable under two names — `utils.x` and
    # `src.utils.x` — because both `src/` and its parent are on the path, and
    # the two are *different module objects*. `data_node` imports
    # `src.utils.BinanceDataProvider` and `src.gateway...Client`, so those are
    # the ones that must be patched; patching the `utils.`/`gateway.` aliases
    # would miss entirely.
    from src.utils.binance_data_provider import BinanceDataProvider
    from src.gateway.binance.client import Client

    Client.ping = lambda self, *a, **k: {}

    def _history(self, symbol, timeframe, end_time=None, limit=500, **kwargs):
        when = end_time if isinstance(end_time, datetime) else datetime(2025, 9, 4)
        return klines_module.klines(symbol, timeframe, when, limit)

    def _latest(self, symbol, timeframe, limit=1000, **kwargs):
        return klines_module.klines(symbol, timeframe, datetime(2025, 9, 4), limit)

    BinanceDataProvider.get_history_klines_with_end_time = _history
    BinanceDataProvider.get_historical_klines = lambda self, symbol, timeframe, *a, **k: klines_module.klines(symbol, timeframe, datetime(2025, 9, 4), k.get("limit", 500))
    BinanceDataProvider.get_latest_data = _latest

    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
