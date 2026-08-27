"""Map a DefuzeX SDK Input onto a TradingAgents analysis request.

The official Case provider emits text only, so a free-form request such as
"Should I buy NVDA on 2024-05-10?" has to become an explicit
``(ticker, trade_date)`` pair. The mapping is deliberately conservative and
documented in the agent README: an unrecognised ticker or a missing date falls
back to the fixed benchmark defaults rather than inventing an instrument.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date

from .runtime import DEFAULT_TICKER, DEFAULT_TRADE_DATE

_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z.\-]{0,5})\b")
_UPPER_TOKEN = re.compile(r"\b([A-Z][A-Z.\-]{1,5})\b")

# Words that look like tickers but never are, so a prompt written in shouty
# prose does not silently redirect the analysis to a different instrument.
_NOT_TICKERS = frozenset(
    {
        "AI", "AND", "ANY", "ASK", "BUY", "CAN", "CEO", "CFO", "EPS", "ETF",
        "FAQ", "FED", "FOR", "GDP", "HOLD", "IPO", "NOT", "NOW", "OR", "P.E",
        "PE", "ROI", "SELL", "SHOULD", "THE", "USD", "WHY", "YOY", "YOU",
    }
)


def _text_of(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("text", "prompt", "question", "input", "content"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    if isinstance(value, (list, tuple)):
        return " ".join(_text_of(item) for item in value)
    return "" if value is None else str(value)


def _valid_date(candidate: str) -> bool:
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def extract_ticker(text: str) -> str:
    """Best-effort ticker extraction with a documented fallback."""
    cashtag = _CASHTAG.search(text)
    if cashtag:
        return cashtag.group(1).upper()

    for token in _UPPER_TOKEN.findall(text):
        if token.upper() not in _NOT_TICKERS:
            return token.upper()
    return DEFAULT_TICKER


def extract_trade_date(text: str) -> str:
    match = _DATE.search(text)
    if match and _valid_date(match.group(1)):
        return match.group(1)
    return DEFAULT_TRADE_DATE


def to_request(payload: object) -> dict[str, str]:
    """Return the ``{"ticker", "trade_date", "request"}`` triple for one Input."""
    if isinstance(payload, Mapping):
        ticker = payload.get("ticker") or payload.get("company_name")
        trade_date = payload.get("trade_date") or payload.get("date")
        if isinstance(ticker, str) and ticker.strip():
            resolved_date = (
                trade_date
                if isinstance(trade_date, str) and _valid_date(trade_date)
                else DEFAULT_TRADE_DATE
            )
            return {
                "ticker": ticker.strip().upper(),
                "trade_date": resolved_date,
                "request": _text_of(payload),
            }

    text = _text_of(payload)
    if not text.strip():
        raise ValueError("Input must contain non-empty text or a 'ticker' field")

    return {
        "ticker": extract_ticker(text),
        "trade_date": extract_trade_date(text),
        "request": text,
    }
