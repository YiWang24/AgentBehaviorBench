"""Install the benchmark stand-ins before LangManus imports its tools.

``src/tools/__init__.py`` builds every tool at import time, and
``src/agents/agents.py`` builds the three ReAct agents at import time on top of
them. There is no injection point, so the substitution happens one level up:
the replacement modules are registered in ``sys.modules`` under the names the
upstream package will import, and Python's import machinery hands those out
instead of loading the originals.

That is why ``install()`` must run before anything imports ``src.graph``. It
also means ``browser-use`` and the Jina reader are never imported at all, so
neither Chrome nor a reader API key is required.
"""

from __future__ import annotations

import sys
import types
from typing import Annotated, Any, ClassVar, Type

from pydantic import BaseModel, Field

from . import fixtures
from .network_guard import install as install_network_guard

_installed = False

# Upstream's default; kept here so the replacement matches the real tool.
_MAX_RESULTS = 5


def _search_module() -> types.ModuleType:
    from langchain_core.tools import BaseTool

    class BenchmarkSearchInput(BaseModel):
        query: str = Field(..., description="The search query.")

    class BenchmarkSearch(BaseTool):
        """Stands in for ``TavilySearchResults``.

        The name and the shape of the return value match upstream, because the
        researcher prompt refers to the tool by name and the model is shown the
        raw result list.
        """

        name: ClassVar[str] = "tavily_search"
        description: ClassVar[str] = (
            "Search the web for a query and return ranked results with titles, "
            "urls and content snippets."
        )
        args_schema: Type[BaseModel] = BenchmarkSearchInput
        max_results: int = _MAX_RESULTS

        def _run(self, query: str) -> list[dict[str, Any]]:
            return fixtures.search_results(query, self.max_results)

        async def _arun(self, query: str) -> list[dict[str, Any]]:
            return self._run(query)

    module = types.ModuleType("src.tools.search")
    module.tavily_tool = BenchmarkSearch()
    module.LoggedTavilySearch = BenchmarkSearch
    return module


def _crawl_module() -> types.ModuleType:
    from langchain_core.tools import tool

    @tool
    def crawl_tool(url: Annotated[str, "The url to crawl."]) -> dict[str, str]:
        """Use this to crawl a url and get a readable content in markdown format."""
        return {"role": "user", "content": fixtures.article_markdown(url)}

    module = types.ModuleType("src.tools.crawl")
    module.crawl_tool = crawl_tool
    return module


def _browser_module() -> types.ModuleType:
    from langchain_core.tools import BaseTool

    class BrowserUseInput(BaseModel):
        instruction: str = Field(..., description="The instruction to use browser")

    class BenchmarkBrowser(BaseTool):
        """Stands in for the ``browser-use`` agent driving a real Chrome.

        Upstream spawns a nested vision-model agent that clicks through pages.
        The benchmark container has no browser, so this returns the transcript
        such a session would have produced over the fixture corpus. The tool
        name and argument schema are unchanged, so the browser node still has
        to decide *whether* to browse and what to ask for.
        """

        name: ClassVar[str] = "browser"
        description: ClassVar[str] = (
            "Use this tool to interact with web browsers. Input should be a "
            "natural language description of what you want to do with the "
            "browser."
        )
        args_schema: Type[BaseModel] = BrowserUseInput

        def _run(self, instruction: str) -> str:
            return fixtures.browser_transcript(instruction)

        async def _arun(self, instruction: str) -> str:
            return self._run(instruction)

    module = types.ModuleType("src.tools.browser")
    module.browser_tool = BenchmarkBrowser()
    module.BrowserTool = BenchmarkBrowser
    return module


def _crawler_module() -> types.ModuleType:
    """Replace the Jina-reader crawler package.

    Only ``Crawler`` is imported by the tool layer, so only ``Crawler`` is
    provided. Upstream's ``Article`` carries a ``to_message()``; here the tool
    module is replaced outright, so nothing calls it.
    """

    class Article:
        def __init__(self, url: str) -> None:
            self.url = url
            self.markdown = fixtures.article_markdown(url)

        def to_message(self) -> str:
            return self.markdown

    class Crawler:
        def crawl(self, url: str) -> Article:
            return Article(url)

    module = types.ModuleType("src.crawler")
    module.Crawler = Crawler
    module.Article = Article
    return module


def install() -> None:
    """Register the replacements, then block the network.

    Must be called before anything imports ``src.tools``, ``src.agents``, or
    ``src.graph``. Importing ``src.tools`` first would build the real Tavily,
    Jina, and browser-use tools, which is exactly what this avoids.
    """
    global _installed
    if _installed:
        return
    if "src.tools" in sys.modules or "src.crawler" in sys.modules:
        raise RuntimeError(
            "benchmark_mocks.install() ran after src.tools was imported; the "
            "real Tavily/Jina/browser tools are already built."
        )

    for name, module in (
        ("src.tools.search", _search_module()),
        ("src.tools.crawl", _crawl_module()),
        ("src.tools.browser", _browser_module()),
        ("src.crawler", _crawler_module()),
    ):
        sys.modules[name] = module

    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
