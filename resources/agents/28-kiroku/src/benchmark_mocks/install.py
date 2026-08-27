"""Replace the search layer and stub the UI toolkit.

`agents/states.py` does `from .search import *`, and `agents/search.py` builds
Tavily, arXiv, PubMed, Wikipedia and a Python REPL at import time. The
replacement is registered in `sys.modules` before `kiroku_app` is imported, so
the upstream nodes call the same functions with the same signatures.

`kiroku_app.py` also imports `gradio` at module scope for its UI. The UI is not
the entry point and gradio is a large dependency, so a stub module stands in.
The stub raises on *any* attribute access, so if a future revision reaches for
gradio on the graph path the failure is loud rather than silent.
"""

from __future__ import annotations

import logging
import sys
import types

from . import fixtures
from .network_guard import install as install_network_guard

_installed = False


class _RefusingModule(types.ModuleType):
    """A module that exists for imports but refuses to be used."""

    def __getattr__(self, name):
        raise RuntimeError(
            f"gradio.{name} was accessed, but the benchmark stubs gradio: the "
            "web UI is not the entry point. If the graph now needs gradio, "
            "install it rather than extending this stub."
        )


def _tools_module() -> types.ModuleType:
    """Stand in for the research-tool layer.

    `agents/__init__.py` imports this eagerly, so it has to exist before
    anything else loads. Wikipedia, arXiv and PubMed answer from the same
    fixture corpus as the search layer; the Python REPL is upstream's real one,
    which runs inside the already-sandboxed container.
    """

    from langchain_core.tools import Tool

    def _lookup(query: str) -> str:
        hits = fixtures.results_for(query, max_results=2)
        return "\n\n".join(
            f"{h['title']}\n{h['url']}\n{h['content']}" for h in hits
        )

    class _BenchmarkTavily:
        """The subset of TavilyClient the search layer uses."""

        def search(self, query, max_results=3, **kwargs):
            return {"results": fixtures.results_for(query, max_results)}

    wikipedia = Tool(
        name="wikipedia",
        func=_lookup,
        description="Look up background on a topic in the benchmark corpus.",
    )
    arxiv = Tool(
        name="arxiv",
        func=_lookup,
        description="Look up preprints in the benchmark corpus.",
    )
    pubmed = Tool(
        name="pub_med",
        func=_lookup,
        description="Look up biomedical literature in the benchmark corpus.",
    )

    from langchain_experimental.utilities import PythonREPL

    repl = PythonREPL()
    python_repl = Tool(
        name="python_repl",
        func=repl.run,
        description="Run Python and return the output.",
    )

    module = types.ModuleType("agents.tools")
    module.tavily = _BenchmarkTavily()
    module.tavily_api_key = None
    module.wikipedia = wikipedia
    module.arxiv = arxiv
    module.pubmed = pubmed
    module.python_repl = python_repl
    module.tools_list = [wikipedia, python_repl, arxiv, pubmed]
    module.tools = {tool.name: tool for tool in module.tools_list}
    return module


def _search_module() -> types.ModuleType:
    def get_additional_info(link):
        return fixtures.additional_info(link)

    def search_query_ideas(query_ideas, cache, max_results=3, search_engine="tavily"):
        """Upstream's contract: returns (content, cache), skipping seen links."""
        content = []
        for query in (query_ideas or {}).get("queries", []):
            if not query:
                continue
            for result in fixtures.results_for(query, max_results):
                link = result["url"].rstrip("/")
                title = result["title"]
                if link in cache or title in cache:
                    continue
                cache.add(link)
                cache.add(title)
                content.append(
                    f"title: {title}, link: {link}, content: {result['content']}"
                    + get_additional_info(link)
                )
        return content, cache

    module = types.ModuleType("agents.search")
    module.get_additional_info = get_additional_info
    module.search_query_ideas = search_query_ideas
    # `agents/states.py` does `from .search import *` with no `__all__`
    # upstream, so it also inherits the names search.py imported — including
    # `logging`, which states.py then calls. Replacing a star-imported module
    # means reproducing its *namespace*, not just its documented API; setting
    # `__all__` here broke states.py with `NameError: name 'logging'`.
    module.logging = logging
    return module


def install() -> None:
    global _installed
    if _installed:
        return
    if "kiroku_app" in sys.modules or "agents.states" in sys.modules:
        raise RuntimeError(
            "benchmark_mocks.install() ran after the agent was imported; the "
            "real Tavily/arXiv/PubMed clients are already built."
        )
    sys.modules["agents.tools"] = _tools_module()
    sys.modules["agents.search"] = _search_module()
    sys.modules["gradio"] = _RefusingModule("gradio")
    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
