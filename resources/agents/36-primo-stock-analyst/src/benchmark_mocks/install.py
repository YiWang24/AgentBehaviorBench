"""Replace the market-data tools with fixtures.

The agent nodes import named functions from `src.tools.yfinance_tool`,
`src.tools.finnhub_tool` and `src.tools.firecrawl_tool` at module scope, so the
replacements are registered in `sys.modules` under those names before the nodes
are imported. `ToolResult` is reused from upstream so the return shape is
identical, and `technical_indicators_tool` (which computes locally from the
fixture price history) is left untouched.
"""

from __future__ import annotations

import sys
import types

from . import fixtures
from .network_guard import install as install_network_guard

_installed = False


def _yfinance_lib_stub():
    """Stub the `yfinance` top-level module.

    `technical_analysis_agent` imports yfinance directly and calls
    `yf.Ticker(symbol).history(...)`, bypassing the tool layer, so the library
    itself is replaced with one whose Ticker serves the fixture price history as
    a DataFrame indexed by date (matching yfinance's shape).
    """

    import pandas as pd

    from . import fixtures

    class _Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, *args, **kwargs):
            rows = fixtures.history(self.symbol)
            frame = pd.DataFrame(rows)
            frame.index = pd.to_datetime(frame["date"])
            frame = frame.rename(columns={
                "open": "Open", "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            return frame[["Open", "High", "Low", "Close", "Volume"]]

        @property
        def info(self):
            return fixtures.company_info(self.symbol)

    module = types.ModuleType("yfinance")
    module.Ticker = _Ticker
    return module


def _yfinance_module():
    from src.tools.utils import ToolResult

    async def get_market_data(symbol, analysis_date=None, period="1y"):
        return ToolResult(success=True, data=fixtures.market_data(symbol, analysis_date))

    async def get_company_info(symbol):
        return ToolResult(success=True, data=fixtures.company_info(symbol))

    module = types.ModuleType("src.tools.yfinance_tool")
    module.get_market_data = get_market_data
    module.get_company_info = get_company_info
    return module


def _finnhub_module():
    from src.tools.utils import ToolResult

    async def get_company_news(symbol, analysis_date=None, *a, **k):
        return ToolResult(success=True, data=fixtures.company_news(symbol, analysis_date))

    async def get_company_profile(symbol):
        return ToolResult(success=True, data=fixtures.company_profile(symbol))

    async def get_company_basic_financials(symbol, metric="all"):
        return ToolResult(success=True, data=fixtures.basic_financials(symbol))

    module = types.ModuleType("src.tools.finnhub_tool")
    module.get_company_news = get_company_news
    module.get_company_profile = get_company_profile
    module.get_company_basic_financials = get_company_basic_financials
    return module


def _firecrawl_module():
    from src.tools.utils import ToolResult

    async def scrape_url(url, *a, **k):
        return ToolResult(success=True, data={"content": fixtures.scrape(url), "url": url})

    async def crawl_website(url, *a, **k):
        return ToolResult(success=True, data={"pages": [{"content": fixtures.scrape(url), "url": url}]})

    module = types.ModuleType("src.tools.firecrawl_tool")
    module.scrape_url = scrape_url
    module.crawl_website = crawl_website
    module.FIRECRAWL_BASE_URL = "https://benchmark.invalid"
    return module


def install() -> None:
    global _installed
    if _installed:
        return
    for name, factory in (
        ("yfinance", _yfinance_lib_stub),
        ("src.tools.yfinance_tool", _yfinance_module),
        ("src.tools.finnhub_tool", _finnhub_module),
        ("src.tools.firecrawl_tool", _firecrawl_module),
    ):
        if name in sys.modules and name != "yfinance":
            raise RuntimeError(f"{name} was imported before install(); the real tool is bound.")
        sys.modules[name] = factory()
    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
