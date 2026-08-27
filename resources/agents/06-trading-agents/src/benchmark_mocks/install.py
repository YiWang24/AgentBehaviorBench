"""Wire the deterministic fixtures into upstream TradingAgents.

Every data tool funnels through ``dataflows.interface.route_to_vendor``, so a
single ``benchmark`` vendor registered for each method covers the whole tool
surface without editing upstream source. Two paths bypass that router and are
patched directly: the symbol-identity lookup and the OHLCV loader behind the
market-data validator.
"""

from __future__ import annotations

import sys

import pandas as pd

from . import market_data
from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


def _benchmark_data_vendors() -> dict[str, str]:
    from tradingagents.dataflows.interface import TOOLS_CATEGORIES

    return {category: market_data.BENCHMARK_VENDOR for category in TOOLS_CATEGORIES}


def _register_vendor_methods() -> None:
    from tradingagents.dataflows import interface

    implementations = {
        "get_stock_data": market_data.stock_data,
        "get_indicators": market_data.indicator,
        "get_fundamentals": market_data.fundamentals,
        "get_balance_sheet": market_data.balance_sheet,
        "get_cashflow": market_data.cashflow,
        "get_income_statement": market_data.income_statement,
        "get_news": market_data.news,
        "get_global_news": market_data.global_news,
        "get_insider_transactions": market_data.insider_transactions,
        "get_macro_indicators": market_data.macro_indicators,
        "get_prediction_markets": market_data.prediction_markets,
    }

    missing = set(interface.VENDOR_METHODS) - set(implementations)
    if missing:
        raise RuntimeError(
            "benchmark_mocks is missing deterministic coverage for: "
            + ", ".join(sorted(missing))
        )

    for method, implementation in implementations.items():
        interface.VENDOR_METHODS.setdefault(method, {})
        interface.VENDOR_METHODS[method][market_data.BENCHMARK_VENDOR] = implementation
    if market_data.BENCHMARK_VENDOR not in interface.VENDOR_LIST:
        interface.VENDOR_LIST.append(market_data.BENCHMARK_VENDOR)


def _patch_symbol_identity() -> None:
    from tradingagents.agents.utils import agent_utils

    def _identity(ticker: str) -> dict:
        market_data.record("symbol-identity", "resolve", ticker)
        return market_data.instrument_identity(ticker)

    # The upstream function is lru_cached; replace the module attribute before
    # anything binds it by name.
    agent_utils.resolve_instrument_identity = _identity


def _patch_social_sources() -> None:
    """Replace the StockTwits and Reddit fetchers.

    The sentiment analyst calls these directly rather than through
    ``route_to_vendor``, and they use ``urllib`` rather than ``requests``, so
    neither the vendor registration nor the HTTP guard covers them. Both the
    source modules and the analyst's already-bound names are patched, because
    the analyst imports the functions by name.
    """
    from tradingagents.dataflows import reddit, stocktwits

    def _stocktwits(ticker, limit=30, timeout=10.0):
        return market_data.stocktwits_messages(ticker, limit)

    def _reddit(ticker, *args, **kwargs):
        return market_data.reddit_posts(ticker)

    stocktwits.fetch_stocktwits_messages = _stocktwits
    reddit.fetch_reddit_posts = _reddit

    module = sys.modules.get("tradingagents.agents.analysts.sentiment_analyst")
    if module is not None:
        module.fetch_stocktwits_messages = _stocktwits
        module.fetch_reddit_posts = _reddit


def _patch_ohlcv_loader() -> None:
    from tradingagents.dataflows import market_data_validator, stockstats_utils

    def _load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
        market_data.record("market-data", "load_ohlcv", f"{symbol} @{curr_date}")
        frame = pd.DataFrame(market_data.ohlcv_rows(symbol, curr_date))
        frame["Date"] = pd.to_datetime(frame["Date"])
        return frame

    stockstats_utils.load_ohlcv = _load_ohlcv
    # market_data_validator imported the symbol directly at module load.
    market_data_validator.load_ohlcv = _load_ohlcv


def install() -> dict[str, str]:
    """Install every mock. Idempotent; returns the benchmark vendor mapping."""
    global _installed

    vendors = _benchmark_data_vendors()
    if _installed:
        return vendors

    _register_vendor_methods()
    _patch_symbol_identity()
    _patch_social_sources()
    _patch_ohlcv_loader()
    install_network_guard()

    _installed = True
    return vendors
