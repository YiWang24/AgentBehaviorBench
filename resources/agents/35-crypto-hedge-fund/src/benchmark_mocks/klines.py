"""Deterministic OHLCV candles for the crypto agent.

Upstream fetches klines from Binance. The benchmark has no market access, so
each (symbol, timeframe) gets a reproducible synthetic series built from a
seeded pseudo-random walk with a mild trend. The columns match upstream's
`COLUMNS`, and the numeric columns are floats so the technical indicators
(MACD, RSI) compute cleanly.

The two symbols are given *opposite* trends so a strategy that reads them has a
real choice: BTCUSDT trends up over the window, ETHUSDT trends down. The walk is
volatile enough that momentum and mean-reversion strategies disagree.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pandas as pd

_INTERVAL_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440,
}

# symbol -> (start price, per-step drift as a fraction)
_PROFILE = {
    "BTCUSDT": (60000.0, +0.004),
    "ETHUSDT": (3000.0, -0.003),
}


def _rand(seed_parts) -> float:
    raw = "|".join(str(p) for p in seed_parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF  # in [0, 1)


def klines(symbol: str, timeframe: str, end_time: datetime, limit: int = 500) -> pd.DataFrame:
    from utils.constants import COLUMNS, NUMERIC_COLUMNS

    start_price, drift = _PROFILE.get(symbol.upper(), (100.0, 0.0))
    step = timedelta(minutes=_INTERVAL_MINUTES.get(timeframe, 60))
    count = min(limit, 500)

    rows = []
    price = start_price
    open_time = end_time - step * count
    for index in range(count):
        shock = (_rand((symbol, timeframe, index)) - 0.5) * 0.02  # +/-1%
        price = max(0.01, price * (1 + drift + shock))
        high = price * (1 + _rand((symbol, timeframe, index, "h")) * 0.01)
        low = price * (1 - _rand((symbol, timeframe, index, "l")) * 0.01)
        open_px = low + (high - low) * _rand((symbol, timeframe, index, "o"))
        close_px = low + (high - low) * _rand((symbol, timeframe, index, "c"))
        volume = 100 + _rand((symbol, timeframe, index, "v")) * 900
        close_time = open_time + step
        rows.append([
            open_time, open_px, high, low, close_px, volume,
            close_time, volume * close_px, 500 + index,
            volume * 0.5, volume * close_px * 0.5, 0,
        ])
        open_time = close_time

    frame = pd.DataFrame(rows, columns=COLUMNS)
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame
