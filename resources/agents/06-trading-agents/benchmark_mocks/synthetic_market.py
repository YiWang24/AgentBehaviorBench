"""Deterministic, seeded synthetic market data for the TradingAgents adapter.

Every function here replaces a real TradingAgents dataflow vendor call (see
``patches.py``). Output is generated from a hash of the requested symbol/date
rather than any network call, so the same request always returns the same
data and the sandbox never depends on Yahoo Finance, FRED, or Polymarket
being reachable. Shapes (headers, CSV layout, markdown sections) mirror the
real vendor functions in ``tradingagents/dataflows/`` closely enough that
downstream prompts and parsers see the same structure they were written for.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

# Curated identity for a handful of common tickers so the representative
# benchmark case (and any obviously popular symbol the SDK Case Provider
# picks) reads naturally. Anything else falls back to a deterministic
# synthetic identity derived from the ticker itself.
_KNOWN_COMPANIES: dict[str, dict[str, Any]] = {
    "NVDA": {"name": "NVIDIA Corporation", "sector": "Technology", "industry": "Semiconductors", "exchange": "NMS", "base_price": 120.0},
    "AAPL": {"name": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "exchange": "NMS", "base_price": 190.0},
    "MSFT": {"name": "Microsoft Corporation", "sector": "Technology", "industry": "Software - Infrastructure", "exchange": "NMS", "base_price": 420.0},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "Communication Services", "industry": "Internet Content & Information", "exchange": "NMS", "base_price": 165.0},
    "AMZN": {"name": "Amazon.com, Inc.", "sector": "Consumer Cyclical", "industry": "Internet Retail", "exchange": "NMS", "base_price": 180.0},
    "META": {"name": "Meta Platforms, Inc.", "sector": "Communication Services", "industry": "Internet Content & Information", "exchange": "NMS", "base_price": 480.0},
    "TSLA": {"name": "Tesla, Inc.", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers", "exchange": "NMS", "base_price": 250.0},
    "SPY": {"name": "SPDR S&P 500 ETF Trust", "sector": "", "industry": "", "exchange": "PCX", "base_price": 520.0},
}

_SECTORS = ["Technology", "Healthcare", "Financial Services", "Industrials", "Energy", "Consumer Defensive"]
_INDUSTRIES = [
    "Software - Application", "Biotechnology", "Banks - Regional",
    "Specialty Industrial Machinery", "Oil & Gas E&P", "Household & Personal Products",
]


def _seed(symbol: str, *extra: str) -> int:
    digest = hashlib.sha256("|".join((symbol.upper(), *extra)).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


class _Prng:
    """Tiny deterministic PRNG (xorshift64) so we don't depend on random's
    global state or numpy for reproducibility across processes."""

    def __init__(self, seed: int) -> None:
        self._state = seed or 0x9E3779B97F4A7C15

    def next(self) -> float:
        x = self._state
        x ^= (x << 13) & 0xFFFFFFFFFFFFFFFF
        x ^= (x >> 7)
        x ^= (x << 17) & 0xFFFFFFFFFFFFFFFF
        self._state = x & 0xFFFFFFFFFFFFFFFF
        return ((x >> 8) & 0xFFFFFF) / float(0xFFFFFF)


def company_identity(symbol: str) -> dict[str, Any]:
    """Deterministic identity metadata for ``symbol`` (real for common tickers)."""
    known = _KNOWN_COMPANIES.get(symbol.upper())
    if known:
        return dict(known)
    seed = _seed(symbol, "identity")
    return {
        "name": f"{symbol.upper()} Holdings, Inc.",
        "sector": _SECTORS[seed % len(_SECTORS)],
        "industry": _INDUSTRIES[(seed // 7) % len(_INDUSTRIES)],
        "exchange": "NMS",
        "base_price": 20.0 + (seed % 48000) / 100.0,
    }


def price_series(symbol: str, end_date: str, years: float = 5.0) -> pd.DataFrame:
    """Deterministic daily OHLCV series, business days only, ending at ``end_date``.

    Index is a ``Date``-named ``DatetimeIndex`` and columns are
    ``Open, High, Low, Close, Adj Close, Volume`` — the same shape
    ``yfinance.Ticker.history``/``yfinance.download`` return.
    """
    identity = company_identity(symbol)
    prng = _Prng(_seed(symbol, "prices"))

    end = pd.Timestamp(end_date).normalize()
    # stdlib timedelta (not pd.DateOffset/pd.Timedelta) so a fractional
    # `years` -- used for the direct yfinance.Ticker.history() shim, which
    # only needs a short window -- doesn't hit dateutil's "non-integer years"
    # rejection or pandas' bare-int deprecation warning.
    start = end - timedelta(days=round(years * 365.25))
    dates = pd.bdate_range(start=start, end=end)

    price = float(identity["base_price"])
    rows: list[tuple[Any, ...]] = []
    for day in dates:
        shock = (prng.next() - 0.5) * 0.04
        price = max(0.5, price * (1 + 0.0002 + shock))
        open_p = price * (1 + (prng.next() - 0.5) * 0.01)
        high = max(open_p, price) * (1 + prng.next() * 0.01)
        low = min(open_p, price) * (1 - prng.next() * 0.01)
        volume = int(1_000_000 + prng.next() * 9_000_000)
        rows.append((day, round(open_p, 2), round(high, 2), round(low, 2), round(price, 2), volume))

    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    df["Adj Close"] = df["Close"]
    df = df.set_index("Date")
    return df[["Open", "High", "Low", "Close", "Adj Close", "Volume"]]


def _reference_date(curr_date: str | None) -> str:
    if curr_date:
        return curr_date
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# tradingagents.dataflows.stockstats_utils.load_ohlcv replacement
# ---------------------------------------------------------------------------


def fake_load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Replacement for ``stockstats_utils.load_ohlcv``.

    Real ``stockstats`` computation then runs on this synthetic series for
    ``get_stock_stats_indicators_window`` and ``build_verified_market_snapshot``
    (both left un-patched), so indicator values are genuinely computed, not
    hand-faked.
    """
    df = price_series(symbol, end_date=curr_date, years=5.0).reset_index()
    return df


# ---------------------------------------------------------------------------
# tradingagents.dataflows.y_finance replacements
# ---------------------------------------------------------------------------


def fake_get_yfin_data_online(symbol: str, start_date: str, end_date: str) -> str:
    df = price_series(symbol, end_date=end_date, years=1.0)
    window = df[(df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))]
    if window.empty:
        window = df.tail(5)

    canonical = symbol.upper()
    header = (
        f"# Stock data for {canonical} from {start_date} to {end_date}\n"
        f"# Total records: {len(window)}\n"
        f"# Data retrieved on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + window.to_csv()


def fake_get_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    identity = company_identity(ticker)
    seed = _seed(ticker, "fundamentals", _reference_date(curr_date))
    prng = _Prng(seed)
    price = identity["base_price"]
    shares_out = 1.5e9 + prng.next() * 8e9
    market_cap = price * shares_out
    eps = round(price / (10 + prng.next() * 30), 2)

    fields = [
        ("Name", identity["name"]),
        ("Sector", identity["sector"]),
        ("Industry", identity["industry"]),
        ("Market Cap", round(market_cap)),
        ("PE Ratio (TTM)", round(price / max(eps, 0.01), 2)),
        ("Forward PE", round(price / max(eps, 0.01) * 0.9, 2)),
        ("EPS (TTM)", eps),
        ("Dividend Yield", round(prng.next() * 0.03, 4)),
        ("Beta", round(0.6 + prng.next() * 1.2, 2)),
        ("52 Week High", round(price * (1.1 + prng.next() * 0.2), 2)),
        ("52 Week Low", round(price * (0.6 + prng.next() * 0.2), 2)),
        ("Revenue (TTM)", round(market_cap * (0.2 + prng.next() * 0.3))),
        ("Profit Margin", round(0.05 + prng.next() * 0.25, 4)),
        ("Return on Equity", round(0.05 + prng.next() * 0.35, 4)),
        ("Debt to Equity", round(prng.next() * 150, 2)),
    ]
    header = (
        f"# Company Fundamentals for {ticker.upper()}\n"
        f"# Data retrieved on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    lines = [f"{label}: {value}" for label, value in fields]
    return header + "\n".join(lines)


def _financial_periods(curr_date: str | None, freq: str, count: int = 4) -> list[pd.Timestamp]:
    end = pd.Timestamp(_reference_date(curr_date)).normalize()
    step_months = 3 if freq.lower() == "quarterly" else 12
    return [end - pd.DateOffset(months=step_months * i) for i in range(count)]


def _financial_frame(
    ticker: str, curr_date: str | None, freq: str, kind: str, row_specs: list[tuple[str, float]]
) -> pd.DataFrame:
    identity = company_identity(ticker)
    prng = _Prng(_seed(ticker, kind, freq, _reference_date(curr_date)))
    scale = identity["base_price"] * 3.0e7  # rough revenue-scale anchor
    periods = _financial_periods(curr_date, freq)

    data: dict[pd.Timestamp, list[float]] = {}
    trend = 1.0
    for period in periods:
        trend *= 0.94 + prng.next() * 0.08  # slight quarter-over-quarter drift, most recent first
        column = []
        for _, multiplier in row_specs:
            noise = 0.9 + prng.next() * 0.2
            column.append(round(scale * multiplier * trend * noise, 0))
        data[period] = column

    index = [label for label, _ in row_specs]
    return pd.DataFrame(data, index=index)


def fake_get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    rows = [
        ("Total Assets", 1.0),
        ("Total Liabilities Net Minority Interest", 0.55),
        ("Total Equity Gross Minority Interest", 0.45),
        ("Cash And Cash Equivalents", 0.12),
        ("Total Debt", 0.28),
    ]
    df = _financial_frame(ticker, curr_date, freq, "balance_sheet", rows)
    header = (
        f"# Balance Sheet data for {ticker.upper()} ({freq})\n"
        f"# Data retrieved on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv()


def fake_get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    rows = [
        ("Operating Cash Flow", 0.22),
        ("Investing Cash Flow", -0.09),
        ("Financing Cash Flow", -0.07),
        ("Free Cash Flow", 0.16),
        ("Capital Expenditure", -0.06),
    ]
    df = _financial_frame(ticker, curr_date, freq, "cashflow", rows)
    header = (
        f"# Cash Flow data for {ticker.upper()} ({freq})\n"
        f"# Data retrieved on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv()


def fake_get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str | None = None) -> str:
    rows = [
        ("Total Revenue", 1.0),
        ("Gross Profit", 0.5),
        ("Operating Income", 0.28),
        ("Net Income", 0.21),
        ("EBITDA", 0.32),
        ("Diluted EPS", 0.0000005),
    ]
    df = _financial_frame(ticker, curr_date, freq, "income_stmt", rows)
    header = (
        f"# Income Statement data for {ticker.upper()} ({freq})\n"
        f"# Data retrieved on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv()


def fake_get_insider_transactions(ticker: str) -> str:
    # Mirrors the real function's own graceful "no filings" branch, which is
    # a common and entirely normal outcome upstream — no fabricated filings.
    return f"No insider transactions reported for symbol '{ticker.upper()}'"


# ---------------------------------------------------------------------------
# tradingagents.dataflows.yfinance_news replacements
# ---------------------------------------------------------------------------

_HEADLINE_TEMPLATES = [
    "{name} shares in focus as analysts weigh {topic}",
    "What to know about {name} ahead of the next earnings update",
    "{name} announces progress on {topic} initiative",
    "Analysts split on {name} outlook amid {topic} concerns",
    "{name} trading volume climbs as investors track {topic}",
]
_TOPICS = ["supply chain conditions", "margin trends", "product roadmap", "competitive pressure", "capital allocation"]
_PUBLISHERS = ["Reuters", "Bloomberg", "MarketWatch", "Benzinga", "The Wall Street Journal"]

_GLOBAL_HEADLINE_TEMPLATES = [
    "Markets digest latest signals on {topic}",
    "Investors weigh {topic} ahead of central bank commentary",
    "{topic} remains in focus as earnings season continues",
    "Global markets steady as traders assess {topic}",
]
_GLOBAL_TOPICS = [
    "Federal Reserve policy expectations", "inflation data", "labor market strength",
    "geopolitical risk", "credit conditions",
]


def fake_get_news_yfinance(ticker: str, start_date: str, end_date: str) -> str:
    identity = company_identity(ticker)
    prng = _Prng(_seed(ticker, "news", start_date, end_date))
    window_start = pd.Timestamp(start_date)
    window_end = pd.Timestamp(end_date)
    span_days = max((window_end - window_start).days, 0)

    articles = []
    for template in _HEADLINE_TEMPLATES[:4]:
        offset_days = int(prng.next() * span_days) if span_days else 0
        pub_date = window_start + timedelta(days=offset_days)
        title = template.format(name=identity["name"], topic=_TOPICS[int(prng.next() * len(_TOPICS))])
        articles.append((title, _PUBLISHERS[int(prng.next() * len(_PUBLISHERS))], pub_date))

    body = ""
    for title, publisher, pub_date in articles:
        body += f"### {title} (source: {publisher})\n"
        body += f"Coverage published {pub_date.strftime('%Y-%m-%d')} discussing {identity['name']}.\n"
        body += f"Link: https://example-news.invalid/{ticker.lower()}/{pub_date.strftime('%Y%m%d')}\n\n"

    return f"## {ticker.upper()} News, from {start_date} to {end_date}:\n\n{body}"


def fake_get_global_news_yfinance(
    curr_date: str, look_back_days: int | None = None, limit: int | None = None
) -> str:
    look_back_days = look_back_days or 7
    curr_dt = pd.Timestamp(curr_date)
    start_dt = curr_dt - timedelta(days=look_back_days)
    prng = _Prng(_seed("__global__", "news", curr_date, str(look_back_days)))

    body = ""
    for template in _GLOBAL_HEADLINE_TEMPLATES:
        offset_days = int(prng.next() * max(look_back_days, 1))
        pub_date = start_dt + timedelta(days=offset_days)
        topic = _GLOBAL_TOPICS[int(prng.next() * len(_GLOBAL_TOPICS))]
        title = template.format(topic=topic)
        publisher = _PUBLISHERS[int(prng.next() * len(_PUBLISHERS))]
        body += f"### {title} (source: {publisher})\n"
        body += f"Macro coverage from {pub_date.strftime('%Y-%m-%d')} on {topic}.\n\n"

    return f"## Global Market News, from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n{body}"


# ---------------------------------------------------------------------------
# tradingagents.dataflows.polymarket replacement
# ---------------------------------------------------------------------------

_PREDICTION_MARKET_TEMPLATES = [
    ("Will the Fed cut rates at its next meeting?", "Yes"),
    ("Will US inflation (CPI YoY) be above 3% next report?", "No"),
    ("Will there be a US recession declared in 2026?", "No"),
    ("Will {topic} beat consensus earnings this quarter?", "Yes"),
]


def fake_get_prediction_markets(topic: str, limit: int | None = None) -> str:
    limit = limit or 4
    prng = _Prng(_seed(topic or "market", "prediction"))
    header = (
        f'## Polymarket prediction markets: "{topic}"\n'
        "Live, market-implied probabilities (higher traded volume = deeper, "
        "more reliable). A probability is the crowd's priced odds of the event, "
        "not a forecast you should take as certain.\n\n"
    )
    lines = []
    for question_template, label in _PREDICTION_MARKET_TEMPLATES[:limit]:
        question = question_template.format(topic=topic)
        prob = 0.35 + prng.next() * 0.5
        volume = int(50_000 + prng.next() * 2_000_000)
        resolve_offset = int(10 + prng.next() * 80)
        resolve_date = (datetime.now(timezone.utc) + timedelta(days=resolve_offset)).strftime("%Y-%m-%d")
        lines.append(f"- **{question}** — {label} {prob:.0%} (${volume:,.0f} volume, resolves {resolve_date})")

    return header + "\n".join(lines) + "\n"
