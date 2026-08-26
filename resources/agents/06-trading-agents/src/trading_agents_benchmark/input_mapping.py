"""Maps a free-text DefuzeX SDK Input to TradingAgents' native call shape.

TradingAgents' Graph entry point is ``propagate(ticker, trade_date,
asset_type)``, not a chat message. The official SDK Case Provider only
generates ``text`` Inputs (see resources/requirements/trading-agents.md), so
the worker must recover a ticker and an analysis date from prose.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timezone

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")

# Common all-caps words/acronyms that are not ticker symbols, so a sentence
# like "the CEO announced an IPO" doesn't get misread as ticker "CEO".
_NOT_TICKERS = {
    "A", "I", "AN", "THE", "IS", "IT", "TO", "OF", "IN", "ON", "FOR", "AND", "OR",
    "AT", "BY", "BE", "AS", "IF", "SO", "NO", "DO", "GO", "UP", "MY", "WE",
    "CEO", "CFO", "CTO", "IPO", "ETF", "GDP", "CPI", "FED", "USA", "USD", "EUR",
    "AI", "ML", "API", "SEC", "FDA", "US", "UK", "EU", "PE", "EPS", "ROI", "ROE",
    "Q1", "Q2", "Q3", "Q4", "BUY", "SELL", "HOLD", "OK", "YTD", "IMO", "TBD",
}

# Common company names the SDK Case Provider might use instead of a raw
# ticker; checked before the regex so "analyze Tesla" resolves correctly.
_COMPANY_ALIASES = {
    "apple": "AAPL", "tesla": "TSLA", "microsoft": "MSFT", "amazon": "AMZN",
    "google": "GOOGL", "alphabet": "GOOGL", "meta": "META", "facebook": "META",
    "nvidia": "NVDA", "netflix": "NFLX", "intel": "INTC",
}

# Falls back to the same ticker TradingAgents' own main.py uses as its
# worked example, so an SDK Input with no discoverable ticker still produces
# a meaningful, on-brand analysis instead of an error.
DEFAULT_TICKER = "NVDA"


def parse_request(raw_input: object) -> tuple[str, str, str]:
    """Return ``(ticker, trade_date, asset_type)`` extracted from an SDK Input."""
    text = _as_text(raw_input)
    ticker = _extract_ticker(text)
    trade_date = _extract_date(text)
    asset_type = "crypto" if _looks_like_crypto(text, ticker) else "stock"
    return ticker, trade_date, asset_type


def _as_text(value: object) -> str:
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("TradingAgents input text must not be empty")
        return value
    if isinstance(value, Mapping):
        for key in ("prompt", "text", "message", "query", "input"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        joined = " ".join(str(v) for v in value.values() if isinstance(v, str))
        if joined.strip():
            return joined
        raise ValueError(
            "TradingAgents object input must contain 'prompt', 'text', "
            "'message', or 'query'"
        )
    raise ValueError("TradingAgents input must be text or a JSON object containing text")


def _extract_ticker(text: str) -> str:
    lowered = text.lower()
    for name, ticker in _COMPANY_ALIASES.items():
        if name in lowered:
            return ticker

    for match in _TICKER_RE.finditer(text):
        candidate = match.group(1)
        base = candidate.split(".")[0]
        if base in _NOT_TICKERS:
            continue
        return candidate

    return DEFAULT_TICKER


def _extract_date(text: str) -> str:
    match = _DATE_RE.search(text)
    if match:
        return match.group(1)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _looks_like_crypto(text: str, ticker: str) -> bool:
    if ticker.upper().endswith(("-USD", "USDT", "USDC")):
        return True
    lowered = text.lower()
    return any(word in lowered for word in ("bitcoin", "ethereum", "crypto currency", "cryptocurrency"))
