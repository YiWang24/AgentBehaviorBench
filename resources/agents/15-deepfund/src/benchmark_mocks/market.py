"""Deterministic market fixtures built from DeepFund's own typed models.

Every figure derives from a hash of the ticker, so the same ticker always yields
the same data and different tickers differ. Nothing here reads the clock or the
network. The upstream Pydantic models are reused rather than hand-rolled dicts,
so a change in their shape fails loudly at construction instead of silently
producing something the analysts cannot read.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta

import pandas as pd

TRACE: list[dict[str, object]] = []


def record(service: str, operation: str, summary: str) -> None:
    TRACE.append({"service": service, "operation": operation, "summary": summary})


def trace_summary() -> list[dict[str, object]]:
    return [dict(entry) for entry in TRACE]


def reset_trace() -> None:
    TRACE.clear()


def _seed(text: str) -> int:
    return int.from_bytes(
        hashlib.sha256(str(text).upper().encode("utf-8")).digest()[:4], "big"
    )


def _as_date(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return datetime(2024, 5, 10)


def candles(ticker: str, trading_date: object, count: int = 120) -> list:
    from apis.common_model import OHLCVCandle

    seed = _seed(ticker)
    base = 20.0 + (seed % 40_000) / 100.0
    end = _as_date(trading_date)

    rows = []
    day = end
    made = 0
    while made < count:
        if day.weekday() < 5:
            index = count - made
            wave = math.sin((index + seed % 11) / 6.0) * base * 0.03
            close = round(base + index * 0.05 + wave, 2)
            spread = round(abs(wave) * 0.4 + 0.35, 2)
            open_price = round(close - wave * 0.25, 2)
            rows.append(
                OHLCVCandle(
                    open=open_price,
                    high=round(max(open_price, close) + spread, 2),
                    low=round(min(open_price, close) - spread, 2),
                    close=close,
                    volume=1_000_000 + (seed % 500) * 1_000 + index * 250,
                    date=day.strftime("%Y-%m-%d"),
                )
            )
            made += 1
        day -= timedelta(days=1)
    return list(reversed(rows))


def candles_df(ticker: str, trading_date: object) -> pd.DataFrame:
    record("market-data", "daily_candles", f"{ticker} @{_as_date(trading_date):%Y-%m-%d}")
    return pd.DataFrame([candle.model_dump() for candle in candles(ticker, trading_date)])


def last_close_price(ticker: str, trading_date: object) -> float:
    record("market-data", "last_close", str(ticker))
    return float(candles(ticker, trading_date, count=1)[0].close)


def news(subject: str, limit: int | None = None) -> list:
    from apis.common_model import MediaNews

    seed = _seed(subject)
    count = max(1, min(int(limit or 3), 5))
    record("news", "get_news", f"{str(subject)[:60]!r} n={count}")
    headlines = (
        "reiterates full-year guidance",
        "expands a long-standing supply agreement",
        "faces questions over near-term demand",
        "reports margin improvement quarter on quarter",
        "announces a leadership change",
    )
    return [
        MediaNews(
            title=f"{subject} {headlines[(seed + index) % len(headlines)]}",
            publish_time="2024-05-09T12:00:00Z",
            publisher="Benchmark Newswire",
            link=f"https://benchmark.invalid/news/{index}",
            summary=(
                "Deterministic benchmark item. Not real journalism and not a "
                "description of any real company."
            ),
        )
        for index in range(count)
    ]


def insider_trades(ticker: str, limit: int | None = None) -> list:
    from apis.alphavantage.api_model import InsiderTrade

    seed = _seed(ticker + "insider")
    count = max(1, min(int(limit or 3), 4))
    record("fundamentals", "insider_trades", f"{ticker} n={count}")
    return [
        InsiderTrade(
            transaction_date="2024-05-0%d" % (index + 1),
            ticker=str(ticker).upper(),
            executive=f"Benchmark Officer {index + 1}",
            executive_title="Officer",
            security_type="Common Stock",
            acquisition_or_disposal="A" if (seed + index) % 2 else "D",
            shares=str((seed + index * 37) % 40_000 + 500),
            share_price=str(round(20 + (seed % 3000) / 100.0, 2)),
        )
        for index in range(count)
    ]


def fundamentals(ticker: str):
    from apis.alphavantage.api_model import Fundamentals

    seed = _seed(ticker + "fundamentals")
    record("fundamentals", "get_fundamentals", str(ticker))

    def value(scale: int, offset: int = 0) -> str:
        return str(round((seed % scale + offset) / 100.0, 2))

    return Fundamentals.model_validate(
        {
            "LatestQuarter": "2024-03-31",
            "MarketCapitalization": str((seed % 900 + 100) * 1_000_000_00),
            "EBITDA": str((seed % 400 + 50) * 1_000_000),
            "PERatio": value(4000, 800),
            "PEGRatio": value(300, 50),
            "BookValue": value(5000),
            "DividendPerShare": value(200),
            "DividendYield": value(50),
            "EPS": value(1500),
            "RevenuePerShareTTM": value(9000),
            "ProfitMargin": value(40),
            "OperatingMarginTTM": value(45),
            "ReturnOnAssetsTTM": value(30),
            "ReturnOnEquityTTM": value(60),
            "RevenueTTM": str((seed % 800 + 100) * 1_000_000),
            "GrossProfitTTM": str((seed % 400 + 50) * 1_000_000),
            "DilutedEPSTTM": value(1500),
            "QuarterlyEarningsGrowthYOY": value(60),
            "QuarterlyRevenueGrowthYOY": value(60),
            "AnalystTargetPrice": value(30000, 2000),
            "AnalystRatingStrongBuy": str(seed % 9 + 1),
            "AnalystRatingBuy": str(seed % 7 + 1),
            "AnalystRatingHold": str(seed % 5 + 1),
            "AnalystRatingSell": str(seed % 3),
            "AnalystRatingStrongSell": str(seed % 2),
            "TrailingPE": value(4000, 800),
            "ForwardPE": value(3500, 700),
            "PriceToSalesRatioTTM": value(900),
            "PriceToBookRatio": value(1200),
            "EVToRevenue": value(900),
            "EVToEBITDA": value(3000),
            "Beta": value(250),
        }
    )


def economic_indicators():
    from apis.alphavantage.api_model import MacroEconomic

    record("macro", "economic_indicators", "fixed panel")
    series = {"date": "2024-04-01", "value": "2.0"}
    return MacroEconomic(
        real_gdp={"data": [series]},
        cpi={"data": [{"date": "2024-04-01", "value": "2.7"}]},
        treasury_yield={"data": [{"date": "2024-04-01", "value": "4.3"}]},
        federal_funds_rate={"data": [{"date": "2024-04-01", "value": "4.25"}]},
        unemployment={"data": [{"date": "2024-04-01", "value": "4.1"}]},
        nonfarm_payrolls={"data": [{"date": "2024-04-01", "value": "158000"}]},
    )
