"""Deterministic market, fundamental, news, and macro fixtures.

Every series is derived from a hash of the symbol, so two runs of the same
ticker produce byte-identical data while different tickers still look
different. Nothing here reads the clock or the network.
"""

from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta

BENCHMARK_VENDOR = "benchmark"

# Fallbacks for tool arguments a model made up. Kept in sync with
# trading_agents_benchmark.runtime so a coerced call still lands on the
# instrument the request was about.
DEFAULT_SYMBOL = "NVDA"
DEFAULT_DATE = date(2024, 5, 10)

TRACE: list[dict[str, object]] = []

_INSTRUMENTS: dict[str, dict[str, str]] = {
    "NVDA": {
        "company_name": "NVIDIA Corporation",
        "sector": "Technology",
        "industry": "Semiconductors",
        "exchange": "NMS",
        "quote_type": "EQUITY",
    },
    "AAPL": {
        "company_name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "exchange": "NMS",
        "quote_type": "EQUITY",
    },
    "MSFT": {
        "company_name": "Microsoft Corporation",
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "exchange": "NMS",
        "quote_type": "EQUITY",
    },
    "TSLA": {
        "company_name": "Tesla, Inc.",
        "sector": "Consumer Cyclical",
        "industry": "Auto Manufacturers",
        "exchange": "NMS",
        "quote_type": "EQUITY",
    },
    "SPY": {
        "company_name": "SPDR S&P 500 ETF Trust",
        "sector": "Financial Services",
        "industry": "Asset Management",
        "exchange": "PCX",
        "quote_type": "ETF",
    },
}

KNOWN_SYMBOLS = tuple(_INSTRUMENTS)


def record(service: str, operation: str, summary: str) -> None:
    """Append one safe mock-trace entry."""
    TRACE.append({"service": service, "operation": operation, "summary": summary})


def trace_summary() -> list[dict[str, object]]:
    """Return a copy of the mock trace collected so far."""
    return [dict(entry) for entry in TRACE]


def reset_trace() -> None:
    TRACE.clear()


def _seed(symbol: str) -> int:
    digest = hashlib.sha256(symbol.upper().encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _base_price(symbol: str) -> float:
    return 20.0 + (_seed(symbol) % 40_000) / 100.0


def _parse_date(value: object) -> date:
    """Coerce whatever the model passed into a usable date.

    Tool arguments come from a language model, so a fixture is routinely handed
    a malformed or entirely non-date string. Upstream's vendor router turns an
    unexpected exception from a core category into an aborted run, so the
    fixtures stay total: unusable input degrades to the fixed benchmark date and
    the coercion is recorded in the mock trace instead of raising.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        record("market-data", "coerce_date", f"unparseable {str(value)[:40]!r}")
        return DEFAULT_DATE


def _parse_symbol(value: object) -> str:
    """Coerce a tool-supplied symbol into a safe, non-empty ticker."""
    text = str(value or "").strip().upper()
    cleaned = "".join(character for character in text if character.isalnum() or character in ".-^=")
    if not cleaned:
        record("market-data", "coerce_symbol", f"unusable {text[:40]!r}")
        return DEFAULT_SYMBOL
    return cleaned[:12]


def _parse_count(value: object, default: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(count, 400))


def _trading_days(end: date, count: int) -> list[date]:
    """Return `count` weekdays ending on or before `end`, oldest first."""
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def ohlcv_rows(symbol: object, curr_date: object, count: int = 120) -> list[dict[str, object]]:
    """Deterministic OHLCV rows ending on or before `curr_date`."""
    symbol = _parse_symbol(symbol)
    count = _parse_count(count, 120)
    seed = _seed(symbol)
    base = _base_price(symbol)
    rows: list[dict[str, object]] = []
    for index, day in enumerate(_trading_days(_parse_date(curr_date), count)):
        drift = index * (0.05 + (seed % 7) / 100.0)
        wave = math.sin((index + seed % 11) / 6.0) * base * 0.03
        close = round(base + drift + wave, 2)
        spread = round(abs(wave) * 0.4 + 0.35, 2)
        open_price = round(close - wave * 0.25, 2)
        rows.append(
            {
                "Date": day.isoformat(),
                "Open": open_price,
                "High": round(max(open_price, close) + spread, 2),
                "Low": round(min(open_price, close) - spread, 2),
                "Close": close,
                "Adj Close": close,
                "Volume": 1_000_000 + (seed % 500) * 1_000 + index * 250,
            }
        )
    return rows


def instrument_identity(symbol: object) -> dict[str, str]:
    """Identity metadata for a ticker; unknown tickers get a generic profile."""
    key = _parse_symbol(symbol)
    if key in _INSTRUMENTS:
        return dict(_INSTRUMENTS[key])
    return {
        "company_name": f"{key} Benchmark Instrument",
        "sector": "Diversified",
        "industry": "Benchmark Fixture",
        "exchange": "BENCH",
        "quote_type": "EQUITY",
    }


def _table(rows: list[dict[str, object]], columns: tuple[str, ...]) -> str:
    header = " | ".join(columns)
    divider = "-" * len(header)
    body = "\n".join(" | ".join(str(row[column]) for column in columns) for row in rows)
    return f"{header}\n{divider}\n{body}"


def stock_data(symbol: object, start_date: object = "", end_date: object = "") -> str:
    symbol = _parse_symbol(symbol)
    end_date = _parse_date(end_date).isoformat()
    start_date = _parse_date(start_date).isoformat()
    window = ohlcv_rows(symbol, end_date, count=180)
    rows = [row for row in window if str(row["Date"]) >= start_date]
    if len(rows) < 2:
        # Both bounds coerced to the same fallback date, or the model asked for
        # an empty range. Show a usable window rather than a single row.
        rows = window[-40:]
        start_date = str(rows[0]["Date"])
    record("market-data", "get_stock_data", f"{symbol} {start_date}..{end_date} rows={len(rows)}")
    table = _table(rows[-40:], ("Date", "Open", "High", "Low", "Close", "Volume"))
    return (
        f"## Benchmark OHLCV for {symbol.upper()} ({start_date} to {end_date})\n"
        f"Deterministic benchmark fixture. Not real market data.\n\n{table}\n"
    )


def indicator(
    symbol: object,
    indicator_name: object = "indicator",
    curr_date: object = "",
    look_back_days: object = 30,
) -> str:
    symbol = _parse_symbol(symbol)
    indicator_name = str(indicator_name or "indicator")[:60]
    curr_date = _parse_date(curr_date).isoformat()
    look_back_days = _parse_count(look_back_days, 30)
    rows = ohlcv_rows(symbol, curr_date, count=max(look_back_days, 30))
    closes = [float(row["Close"]) for row in rows]
    window = closes[-min(len(closes), look_back_days) :]
    mean = sum(window) / len(window)
    spread = max(window) - min(window)
    record("market-data", "get_indicators", f"{symbol} {indicator_name} @{curr_date}")
    return (
        f"## {indicator_name} for {symbol.upper()} as of {curr_date}\n"
        f"Deterministic benchmark fixture over the last {len(window)} sessions.\n"
        f"- latest close: {closes[-1]:.2f}\n"
        f"- mean: {mean:.2f}\n"
        f"- range: {spread:.2f}\n"
        f"- reading: {'above' if closes[-1] >= mean else 'below'} the window mean\n"
    )


def fundamentals(symbol: object, curr_date: object = "") -> str:
    symbol = _parse_symbol(symbol)
    curr_date = _parse_date(curr_date).isoformat()
    seed = _seed(symbol)
    record("fundamentals", "get_fundamentals", f"{symbol} @{curr_date}")
    return (
        f"## Fundamentals for {symbol.upper()} as of {curr_date}\n"
        "Deterministic benchmark fixture. Not real filings.\n"
        f"- market cap: ${(seed % 900 + 100) / 10:.1f}B\n"
        f"- trailing P/E: {(seed % 400) / 10 + 8:.1f}\n"
        f"- gross margin: {(seed % 45) + 30}%\n"
        f"- revenue growth YoY: {(seed % 60) - 10}%\n"
        f"- free cash flow: ${(seed % 300) / 10:.1f}B\n"
    )


def _statement(kind: str, symbol: object, freq: object, curr_date: object) -> str:
    symbol = _parse_symbol(symbol)
    freq = str(freq or "annual")[:20]
    curr_date = _parse_date(curr_date).isoformat()
    seed = _seed(symbol + kind)
    record("fundamentals", kind, f"{symbol} freq={freq} @{curr_date}")
    lines = "\n".join(
        f"- {label}: ${(seed >> shift) % 5000 / 10:.1f}B"
        for shift, label in enumerate(("total", "operating", "investing", "financing"))
    )
    return (
        f"## {kind.replace('_', ' ').title()} for {symbol.upper()} "
        f"({freq}, as of {curr_date})\n"
        f"Deterministic benchmark fixture.\n{lines}\n"
    )


def balance_sheet(symbol: object, freq: object = "annual", curr_date: object = "") -> str:
    return _statement("balance_sheet", symbol, freq, curr_date)


def cashflow(symbol: object, freq: object = "annual", curr_date: object = "") -> str:
    return _statement("cashflow", symbol, freq, curr_date)


def income_statement(symbol: object, freq: object = "annual", curr_date: object = "") -> str:
    return _statement("income_statement", symbol, freq, curr_date)


def news(symbol: object, curr_date: object = "", *args, **kwargs) -> str:
    symbol = _parse_symbol(symbol)
    curr_date = _parse_date(curr_date).isoformat()
    seed = _seed(symbol)
    identity = instrument_identity(symbol)
    record("news", "get_news", f"{symbol} @{curr_date}")
    headlines = [
        f"{identity['company_name']} reiterates full-year guidance",
        f"Analysts debate {identity['industry'].lower()} demand into next quarter",
        f"{symbol.upper()} supply agreement extended with a long-standing partner",
    ]
    body = "\n".join(
        f"- [{curr_date}] {headline} (benchmark fixture #{(seed + index) % 1000})"
        for index, headline in enumerate(headlines)
    )
    return (
        f"## Ticker news for {symbol.upper()} as of {curr_date}\n"
        f"Deterministic benchmark fixture. Not real journalism.\n{body}\n"
    )


def global_news(curr_date: object = "", *args, **kwargs) -> str:
    curr_date = _parse_date(curr_date).isoformat()
    record("news", "get_global_news", f"@{curr_date}")
    return (
        f"## Global macro headlines as of {curr_date}\n"
        "Deterministic benchmark fixture. Not real journalism.\n"
        "- Central banks hold policy rates steady, signalling data dependence\n"
        "- Broad equity indices close mixed on light volume\n"
        "- Energy prices range-bound; freight rates stable week over week\n"
    )


def insider_transactions(symbol: object, curr_date: object = "", *args, **kwargs) -> str:
    symbol = _parse_symbol(symbol)
    curr_date = _parse_date(curr_date).isoformat()
    seed = _seed(symbol + "insider")
    record("fundamentals", "get_insider_transactions", f"{symbol} @{curr_date}")
    return (
        f"## Insider transactions for {symbol.upper()} as of {curr_date}\n"
        "Deterministic benchmark fixture.\n"
        f"- Officer sale: {seed % 40_000 + 1_000} shares under a pre-set plan\n"
        f"- Director purchase: {seed % 9_000 + 500} shares on the open market\n"
    )


def macro_indicators(*args, **kwargs) -> str:
    record("macro", "get_macro_indicators", "fixed macro panel")
    return (
        "## Macro indicators\n"
        "Deterministic benchmark fixture. Not real FRED data.\n"
        "- policy rate: 4.25%\n"
        "- headline CPI YoY: 2.7%\n"
        "- unemployment: 4.1%\n"
        "- real GDP growth QoQ annualised: 2.0%\n"
    )


def prediction_markets(topic: object = "", limit: object = 5, *args, **kwargs) -> str:
    topic = str(topic or "")[:80]
    limit = _parse_count(limit, 5)
    record("prediction-markets", "get_prediction_markets", f"topic={topic!r} limit={limit}")
    return (
        f"## Prediction markets for {topic or 'general macro'}\n"
        "Deterministic benchmark fixture. Not real Polymarket data.\n"
        "- rate cut by next meeting: 32%\n"
        "- recession called within 12 months: 21%\n"
        "- index closes the year higher: 58%\n"
    )


def stocktwits_messages(ticker: object, limit: object = 30, *args, **kwargs) -> str:
    """Deterministic stand-in for `dataflows.stocktwits.fetch_stocktwits_messages`."""
    symbol = _parse_symbol(ticker)
    limit = _parse_count(limit, 30)
    identity = instrument_identity(symbol)
    seed = _seed(symbol + "stocktwits")
    sentiments = ("Bullish", "Bearish", "Bullish", "Neutral")
    lines = [
        f"- [{sentiments[(seed + index) % len(sentiments)]}] "
        f"Watching {symbol} into the close; {identity['industry'].lower()} flow looks steady. "
        f"(benchmark fixture #{(seed + index) % 1000})"
        for index in range(min(limit, 6))
    ]
    record("social", "stocktwits", f"{symbol} limit={limit}")
    return (
        f"## StockTwits messages for {symbol}\n"
        "Deterministic benchmark fixture. Not real community posts.\n"
        + "\n".join(lines)
        + "\n"
    )


def reddit_posts(ticker: object, *args, **kwargs) -> str:
    """Deterministic stand-in for `dataflows.reddit.fetch_reddit_posts`."""
    symbol = _parse_symbol(ticker)
    seed = _seed(symbol + "reddit")
    subreddits = ("wallstreetbets", "stocks", "investing")
    lines = [
        f"- r/{subreddit}: \"{symbol} thread — mixed views on the setup\" "
        f"(score {seed % 900 + 20}, {seed % 120 + 5} comments, benchmark fixture)"
        for subreddit in subreddits
    ]
    record("social", "reddit", symbol)
    return (
        f"## Reddit discussion for {symbol}\n"
        "Deterministic benchmark fixture. Not real community posts.\n"
        + "\n".join(lines)
        + "\n"
    )
