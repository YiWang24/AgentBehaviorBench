"""Direct tests for benchmark_mocks against the real vendored tradingagents package.

apply_patches() must run before any `tradingagents` import anywhere in the
process (see benchmark_mocks/patches.py), so it happens at module import
time here, before the `import tradingagents...` statements below.
"""

from __future__ import annotations

import pandas as pd
import pytest

from benchmark_mocks import apply_patches

apply_patches()

import yfinance as yf  # noqa: E402

import tradingagents.dataflows.fred as fred  # noqa: E402
import tradingagents.dataflows.polymarket as polymarket  # noqa: E402
import tradingagents.dataflows.stockstats_utils as stockstats_utils  # noqa: E402
import tradingagents.dataflows.y_finance as y_finance  # noqa: E402
import tradingagents.dataflows.yfinance_news as yfinance_news  # noqa: E402

CURR_DATE = "2024-05-10"
TICKERS = ["NVDA", "ZZZZ-SYNTHETIC"]


def test_apply_patches_is_idempotent() -> None:
    apply_patches()
    apply_patches()


def test_yfinance_ticker_is_faked() -> None:
    assert yf.Ticker.__module__.startswith("benchmark_mocks")


@pytest.mark.parametrize("ticker", TICKERS)
def test_fake_ticker_info_and_history(ticker: str) -> None:
    stock = yf.Ticker(ticker)
    info = stock.info
    assert info["longName"]
    assert info["quoteType"] == "EQUITY"

    history = stock.history(start="2024-05-01", end="2024-05-10")
    assert not history.empty
    assert "Close" in history.columns
    assert (history["Close"] > 0).all()


@pytest.mark.parametrize("ticker", TICKERS)
def test_load_ohlcv_returns_usable_frame(ticker: str) -> None:
    df = stockstats_utils.load_ohlcv(ticker, CURR_DATE)
    assert not df.empty
    assert list(df.columns[:5]) == ["Date", "Open", "High", "Low", "Close"]
    assert pd.api.types.is_numeric_dtype(df["Close"])
    # 5y of business days should comfortably clear the 200-SMA window.
    assert len(df) > 200
    assert (pd.to_datetime(df["Date"]) <= pd.Timestamp(CURR_DATE)).all()


@pytest.mark.parametrize("ticker", TICKERS)
def test_get_stock_stats_indicators_window_runs_real_stockstats(ticker: str) -> None:
    # get_stock_stats_indicators_window itself is NOT patched -- this exercises
    # real stockstats computation on top of the synthetic OHLCV series.
    result = y_finance.get_stock_stats_indicators_window(ticker, "close_50_sma", CURR_DATE, 5)
    assert "close_50_sma values" in result
    assert CURR_DATE in result


@pytest.mark.parametrize("ticker", TICKERS)
def test_yfin_data_online(ticker: str) -> None:
    result = y_finance.get_YFin_data_online(ticker, "2024-04-01", "2024-05-10")
    assert f"Stock data for {ticker.upper()}" in result
    assert "Close" in result


@pytest.mark.parametrize("ticker", TICKERS)
def test_fundamentals_and_financial_statements(ticker: str) -> None:
    fundamentals = y_finance.get_fundamentals(ticker, CURR_DATE)
    assert "Company Fundamentals" in fundamentals
    assert "Sector:" in fundamentals

    for freq in ("quarterly", "annual"):
        balance_sheet = y_finance.get_balance_sheet(ticker, freq, CURR_DATE)
        assert "Balance Sheet data" in balance_sheet
        cashflow = y_finance.get_cashflow(ticker, freq, CURR_DATE)
        assert "Cash Flow data" in cashflow
        income = y_finance.get_income_statement(ticker, freq, CURR_DATE)
        assert "Income Statement data" in income


def test_insider_transactions_reports_none_gracefully() -> None:
    result = y_finance.get_insider_transactions("NVDA")
    assert "No insider transactions reported" in result


def test_verified_market_snapshot_runs_real_stockstats() -> None:
    from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot

    snapshot = build_verified_market_snapshot("NVDA", CURR_DATE)
    assert "Verified market data snapshot for NVDA" in snapshot
    assert "Latest verified OHLCV row" in snapshot
    assert "close_50_sma" in snapshot


def test_news_and_global_news_are_windowed() -> None:
    news = yfinance_news.get_news_yfinance("NVDA", "2024-05-01", "2024-05-10")
    assert "NVDA News" in news
    assert "2024-05" in news

    global_news = yfinance_news.get_global_news_yfinance(CURR_DATE, look_back_days=7, limit=4)
    assert "Global Market News" in global_news


def test_prediction_markets_returns_canned_markets() -> None:
    result = polymarket.get_prediction_markets("Fed rate cut", limit=3)
    assert "Polymarket prediction markets" in result
    assert "%" in result


def test_fred_is_left_gracefully_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(fred.FredNotConfiguredError):
        fred.get_api_key()


def test_requests_network_safety_net_blocks_unmocked_calls() -> None:
    import requests

    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get("https://example.invalid/anything")
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.Session().get("https://example.invalid/anything")
