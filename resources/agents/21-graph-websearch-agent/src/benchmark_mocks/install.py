"""Replace the Serper search and the page scraper.

``agent_graph/graph.py`` imports both by name at module scope, so the
substitution registers replacement modules in ``sys.modules`` before that
import happens. The function signatures and the *shape* of what they return —
a formatted result listing, a ``HumanMessage`` of page text — are reproduced
exactly, because the agents parse them.
"""

from __future__ import annotations

import json
import sys
import types

from . import fixtures
from .network_guard import install as install_network_guard

_installed = False


def _format_results(organic_results) -> str:
    """Byte-for-byte the upstream formatter, so prompts are unchanged."""
    result_strings = []
    for result in organic_results:
        title = result.get("title", "No Title")
        link = result.get("link", "#")
        snippet = result.get("snippet", "No snippet available.")
        result_strings.append(f"Title: {title}\nLink: {link}\nSnippet: {snippet}\n---")
    return "\n".join(result_strings)


def _search_term(plan) -> str:
    """Upstream reads the search term out of the planner's JSON reply."""
    try:
        data = json.loads(plan().content)
    except Exception:  # noqa: BLE001 - a malformed plan is the agent's problem
        return ""
    if isinstance(data, dict):
        value = data.get("search_term")
        if isinstance(value, str):
            return value
    return ""


def _serper_module() -> types.ModuleType:
    def get_google_serper(state, plan):
        term = _search_term(plan)
        if not term:
            # Upstream surfaces a malformed plan as a key error in the state
            # rather than raising; keep that behaviour.
            return {**state, "serper_response": "Key error occurred: 'search_term'"}
        formatted = _format_results(fixtures.organic(term))
        return {**state, "serper_response": formatted}

    module = types.ModuleType("tools.google_serper")
    module.get_google_serper = get_google_serper
    module.format_results = _format_results
    return module


def _scraper_module() -> types.ModuleType:
    from langchain_core.messages import HumanMessage

    def scrape_website(state, research=None):
        try:
            data = json.loads(research().content)
            url = data.get("selected_page_url") or data.get("error") or ""
        except Exception:  # noqa: BLE001
            url = ""
        # Upstream truncates at 4000 characters and serialises with str(),
        # not json.dumps(). The agents parse what they are given, so the
        # formatting is reproduced rather than improved.
        content = fixtures.page_body(url)[:4000]
        state["scraper_response"].append(
            HumanMessage(role="system", content=str({"source": url, "content": content}))
        )
        return {"scraper_response": state["scraper_response"]}

    module = types.ModuleType("tools.basic_scraper")
    module.scrape_website = scrape_website
    module.is_garbled = lambda text: False
    return module


def install() -> None:
    global _installed
    if _installed:
        return
    if "agent_graph.graph" in sys.modules:
        raise RuntimeError(
            "benchmark_mocks.install() ran after agent_graph.graph was "
            "imported; the real Serper and scraper are already bound."
        )
    for name, module in (
        ("tools.google_serper", _serper_module()),
        ("tools.basic_scraper", _scraper_module()),
    ):
        sys.modules[name] = module
    install_network_guard()
    _installed = True


def installed() -> bool:
    return _installed
