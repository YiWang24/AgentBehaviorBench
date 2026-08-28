"""Wire the deterministic fixtures into DeepFund.

Every analyst builds its own `Router` and then calls through it, so replacing
the Router class in `apis.router` before the analyst modules are imported covers
the whole market-data surface — prices, fundamentals, news, insider trades, and
macro indicators — in one place.
"""

from __future__ import annotations

from . import market
from .network_guard import install as install_network_guard

_installed = False


def installed() -> bool:
    return _installed


class BenchmarkRouter:
    """Offline stand-in for `apis.router.Router`, same method surface."""

    def __init__(self, source: object = None) -> None:
        self.source = source

    def get_us_stock_news(self, ticker, trading_date=None, news_count=None):
        return market.news(ticker, news_count)

    def get_market_news(self, topic, trading_date=None, news_count=None):
        return market.news(topic, news_count)

    def get_us_stock_insider_trades(self, ticker, trading_date=None, limit=None):
        return market.insider_trades(ticker, limit)

    def get_us_stock_daily_candles_df(self, ticker, trading_date=None):
        return market.candles_df(ticker, trading_date)

    def get_us_stock_last_close_price(self, ticker, trading_date=None):
        return market.last_close_price(ticker, trading_date)

    def get_us_stock_fundamentals(self, ticker):
        return market.fundamentals(ticker)

    def get_us_economic_indicators(self):
        return market.economic_indicators()


def _patch_router() -> None:
    from apis import router as router_module

    router_module.Router = BenchmarkRouter


def install() -> None:
    """Install every mock. Idempotent.

    Must run before `agents.registry` imports the analysts, because each binds
    `Router` by name at module import time.
    """
    global _installed
    if _installed:
        return

    _patch_router()
    install_network_guard()
    _installed = True
