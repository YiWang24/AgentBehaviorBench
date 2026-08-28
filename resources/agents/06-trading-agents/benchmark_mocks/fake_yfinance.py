"""Fake replacement for ``yfinance.Ticker``.

Two call sites in the vendored ``tradingagents`` package talk to yfinance
directly instead of going through ``dataflows.y_finance`` (which is patched
separately in ``patches.py``):

- ``agents/utils/agent_utils.py:resolve_instrument_identity`` reads ``.info``.
- ``graph/trading_graph.py:_fetch_returns`` reads ``.history(start=, end=)``.

Both only need a small, well-formed surface, so this fake covers exactly
``.info`` and ``.history`` rather than the full yfinance API.
"""

from __future__ import annotations

import pandas as pd

from .synthetic_market import company_identity, price_series


class FakeTicker:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def info(self) -> dict:
        identity = company_identity(self.symbol)
        return {
            "longName": identity["name"],
            "shortName": identity["name"],
            "sector": identity["sector"],
            "industry": identity["industry"],
            "exchange": identity["exchange"],
            "quoteType": "EQUITY",
        }

    def history(self, start: str | None = None, end: str | None = None, **_kwargs) -> pd.DataFrame:
        end_date = end or pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
        df = price_series(self.symbol, end_date=str(end_date)[:10], years=0.5)
        if start:
            df = df[df.index >= pd.Timestamp(start)]
        if end:
            # yfinance treats ``end`` as exclusive.
            df = df[df.index < pd.Timestamp(str(end)[:10])]
        return df
