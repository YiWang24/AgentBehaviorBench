"""Applies every non-LLM network mock. Call ``apply_patches()`` before any
``import tradingagents...`` statement anywhere in the process — the worker
entry point and the langgraph.json factory both do this first.

Patches are applied at each vendor module's own origin (e.g.
``tradingagents.dataflows.y_finance.get_balance_sheet``) rather than by
reimplementing the LangChain ``@tool`` wrappers, so import order matters:
a module must be patched *before* any other module does
``from .that_module import name``, or the importer keeps the original
function. ``apply_patches`` is idempotent and safe to call more than once.
"""

from __future__ import annotations

_applied = False


def apply_patches() -> None:
    global _applied
    if _applied:
        return
    _patch_requests_safety_net()
    _patch_yfinance()
    _patch_dataflows()
    _applied = True


def _patch_yfinance() -> None:
    import yfinance as yf

    from .fake_yfinance import FakeTicker

    yf.Ticker = FakeTicker


def _patch_dataflows() -> None:
    from . import synthetic_market as sm

    # stockstats_utils first: y_finance and market_data_validator both import
    # `load_ohlcv` by name from it, so the patch must land before either of
    # those modules is imported for the first time.
    import tradingagents.dataflows.stockstats_utils as stockstats_utils

    stockstats_utils.load_ohlcv = sm.fake_load_ohlcv

    import tradingagents.dataflows.y_finance as y_finance

    y_finance.get_YFin_data_online = sm.fake_get_yfin_data_online
    y_finance.get_fundamentals = sm.fake_get_fundamentals
    y_finance.get_balance_sheet = sm.fake_get_balance_sheet
    y_finance.get_cashflow = sm.fake_get_cashflow
    y_finance.get_income_statement = sm.fake_get_income_statement
    y_finance.get_insider_transactions = sm.fake_get_insider_transactions

    import tradingagents.dataflows.yfinance_news as yfinance_news

    yfinance_news.get_news_yfinance = sm.fake_get_news_yfinance
    yfinance_news.get_global_news_yfinance = sm.fake_get_global_news_yfinance

    import tradingagents.dataflows.polymarket as polymarket

    polymarket.get_prediction_markets = sm.fake_get_prediction_markets


def _patch_requests_safety_net() -> None:
    """Block any request this adapter did not explicitly mock.

    FRED is intentionally left unconfigured (no ``FRED_API_KEY``) rather than
    mocked: ``tradingagents.dataflows.fred.get_api_key`` raises
    ``FredNotConfiguredError`` before any HTTP call, which the router already
    treats as a graceful "vendor unavailable" outcome. Everything else
    (alpha_vantage, reddit, stocktwits — none of which are reachable through
    the default vendor config) is blocked here as defense in depth so a
    misconfiguration can never fall back to a real network call.
    """
    import requests

    def _blocked(method: str, url: str, *_args, **_kwargs):
        raise requests.exceptions.ConnectionError(
            "AgentBench sandbox: outbound network is disabled for non-model "
            f"traffic (blocked {method} {url!r}). This host/path has no "
            "benchmark_mocks fixture."
        )

    def _blocked_session_request(self, method, url, *args, **kwargs):
        return _blocked(method, url)

    requests.get = lambda url, *a, **k: _blocked("GET", url)
    requests.post = lambda url, *a, **k: _blocked("POST", url)
    requests.Session.request = _blocked_session_request
