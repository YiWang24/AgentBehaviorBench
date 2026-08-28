"""Deterministic market data for the stock-analysis agent.

Upstream pulls prices from yfinance, news and financials from Finnhub, and
scrapes articles with Firecrawl. All are replaced by fixtures keyed on the
ticker. Two tickers are provided with *opposite* stories so the analysis has a
real choice: BENC trends up with improving financials and positive news; DFUZ
trends down with a profit warning.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

_PROFILE = {
    "BENC": {
        "name": "Benchmark Industries Inc.",
        "sector": "Technology",
        "industry": "Software",
        "trend": +0.6,       # per-day drift, dollars
        "start": 120.0,
        "pe": 24.5,
        "sentiment": "positive",
        "headline": "Benchmark Industries raises full-year guidance on strong cloud demand",
        "body": (
            "Benchmark Industries reported quarterly revenue above consensus and "
            "lifted its full-year outlook, citing accelerating cloud adoption and "
            "improving operating margins. Management highlighted a growing backlog."
        ),
    },
    "DFUZ": {
        "name": "Defuze Corp.",
        "sector": "Consumer Cyclical",
        "industry": "Retail",
        "trend": -0.5,
        "start": 84.0,
        "pe": 11.2,
        "sentiment": "negative",
        "headline": "Defuze Corp warns on profit as demand softens",
        "body": (
            "Defuze Corp cut its profit forecast for the second time this year, "
            "pointing to weakening consumer demand and rising inventory. Analysts "
            "noted margin pressure and a slowing sales trend."
        ),
    },
}


def _rand(*parts) -> float:
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big") / 0xFFFFFFFF


def _profile(symbol: str) -> dict:
    return _PROFILE.get(symbol.upper(), {
        "name": f"{symbol.upper()} Corp.", "sector": "N/A", "industry": "N/A",
        "trend": 0.0, "start": 50.0, "pe": 15.0, "sentiment": "neutral",
        "headline": f"No benchmark news for {symbol.upper()}",
        "body": "The benchmark corpus has no article for this ticker.",
    })


def history(symbol: str, days: int = 200, end: datetime | None = None) -> list[dict]:
    p = _profile(symbol)
    end = end or datetime(2026, 8, 24)
    rows = []
    price = p["start"]
    for index in range(days):
        shock = (_rand(symbol, index) - 0.5) * 2.0
        price = max(1.0, price + p["trend"] + shock)
        day = end - timedelta(days=days - index)
        high = price + _rand(symbol, index, "h") * 1.5
        low = price - _rand(symbol, index, "l") * 1.5
        rows.append({
            "date": day.strftime("%Y-%m-%d"),
            "open": round(low + (high - low) * _rand(symbol, index, "o"), 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(price, 2),
            "volume": int(1_000_000 + _rand(symbol, index, "v") * 5_000_000),
        })
    return rows


def market_data(symbol: str, analysis_date: str | None = None) -> dict:
    rows = history(symbol)
    latest, previous = rows[-1], rows[-2]
    change = round(latest["close"] - previous["close"], 2)
    return {
        "symbol": symbol.upper(),
        "date": latest["date"],
        "current_price": latest["close"],
        "price_data": {
            "open": latest["open"], "high": latest["high"], "low": latest["low"],
            "close": latest["close"], "volume": latest["volume"],
            "previous_close": previous["close"], "price_change": change,
            "price_change_pct": round(change / previous["close"] * 100, 2),
        },
        "historical_data": rows,
    }


def company_info(symbol: str) -> dict:
    p = _profile(symbol)
    return {
        "symbol": symbol.upper(), "name": p["name"], "sector": p["sector"],
        "industry": p["industry"], "market_cap": 5_000_000_000, "pe_ratio": p["pe"],
        "description": f"{p['name']} is a benchmark fixture company; it does not exist.",
    }


def company_profile(symbol: str) -> dict:
    p = _profile(symbol)
    return {"name": p["name"], "ticker": symbol.upper(), "finnhubIndustry": p["industry"],
            "country": "US", "exchange": "BENCHMARK", "marketCapitalization": 5000.0}


def basic_financials(symbol: str) -> dict:
    p = _profile(symbol)
    up = p["trend"] > 0
    return {"metric": {
        "peBasicExclExtraTTM": p["pe"],
        "revenueGrowthTTMYoy": 12.0 if up else -6.0,
        "netProfitMarginTTM": 18.0 if up else 4.0,
        "roeTTM": 22.0 if up else 5.0,
        "52WeekHigh": p["start"] * 1.3, "52WeekLow": p["start"] * 0.7,
    }}


def company_news(symbol: str, analysis_date: str | None = None) -> list[dict]:
    p = _profile(symbol)
    return [{
        "headline": p["headline"],
        "summary": p["body"][:160],
        "url": f"https://benchmark.invalid/news/{symbol.lower()}",
        "source": "Benchmark Wire",
        "datetime": int(datetime(2026, 8, 23).timestamp()),
        "sentiment": p["sentiment"],
    }]


def scrape(url: str) -> str:
    for symbol, p in _PROFILE.items():
        if symbol.lower() in str(url).lower():
            return f"# {p['headline']}\n\n{p['body']}\n\nSource: {url}"
    return "The benchmark corpus has no article at this address."
