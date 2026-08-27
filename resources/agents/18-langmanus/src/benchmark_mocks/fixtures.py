"""Deterministic stand-ins for the three services LangManus reaches.

Upstream researches with Tavily, reads pages through Jina's reader, and drives
a real Chrome through ``browser-use``. None of the three can run under the
benchmark: the container has no browser, and the only permitted egress is the
model provider. Each is replaced by a fixture that keeps the *shape* of the
upstream result — a ranked result list, a markdown article, a browser
transcript — so the graph's routing and grounding behaviour stays observable.

Everything is served from the reserved ``benchmark.invalid`` domain so no
output can be mistaken for a real source.
"""

from __future__ import annotations

import hashlib
import re

_TOKEN = re.compile(r"[A-Za-z0-9]+")

# Topics deliberately differ from one another so a judge can tell which one the
# agent actually retrieved, rather than every result looking alike.
_ARTICLES: dict[str, dict[str, str]] = {
    "planning": {
        "title": "Decomposing a research task into a plan",
        "body": (
            "A plan is worth writing when a task has more than one unknown. "
            "The benchmark corpus records three habits: name the unknowns "
            "before choosing tools, assign each step to the cheapest agent "
            "that can finish it, and stop planning once the next action is "
            "obvious. Plans that enumerate more than about seven steps tend "
            "to be re-planned before step four."
        ),
    },
    "retrieval": {
        "title": "When search beats recall",
        "body": (
            "Search earns its cost when the answer changes over time or is "
            "narrower than the model's training distribution. For stable, "
            "widely documented facts the retrieval round trip usually adds "
            "latency without adding accuracy. The benchmark corpus reports a "
            "crossover around questions whose answer would have changed in "
            "the last eighteen months."
        ),
    },
    "code": {
        "title": "Running generated code safely",
        "body": (
            "Generated code should execute where a mistake is cheap: a "
            "container with no credentials, no writable system paths, and no "
            "outbound network. The benchmark corpus notes that agents which "
            "can read their own stderr recover from roughly two thirds of "
            "first-attempt failures without further prompting."
        ),
    },
    "reporting": {
        "title": "Writing the answer a reader can check",
        "body": (
            "A report is checkable when every claim traces to something the "
            "reader can open. The benchmark corpus recommends naming the "
            "source next to the claim rather than collecting links at the "
            "end, and stating plainly which questions the evidence did not "
            "settle."
        ),
    },
}

_ORDER = list(_ARTICLES)


def _rank(query: str) -> list[str]:
    """Order topics by shared vocabulary with the query, ties broken stably."""
    terms = set(_TOKEN.findall(str(query or "").lower()))
    scored = []
    for key in _ORDER:
        article = _ARTICLES[key]
        words = set(_TOKEN.findall((key + " " + article["title"] + " " + article["body"]).lower()))
        scored.append((-len(terms & words), _ORDER.index(key), key))
    return [key for _, _, key in sorted(scored)]


def url_for(key: str) -> str:
    return f"https://benchmark.invalid/articles/{key}"


def search_results(query: str, max_results: int = 5) -> list[dict[str, object]]:
    """A Tavily-shaped result list."""
    results = []
    for position, key in enumerate(_rank(query)[: max(1, max_results)]):
        article = _ARTICLES[key]
        results.append(
            {
                "title": article["title"],
                "url": url_for(key),
                "content": article["body"][:280],
                "score": round(1.0 - 0.13 * position, 3),
            }
        )
    return results


def article_markdown(url: str) -> str:
    """The page a crawl of ``url`` returns, in markdown."""
    for key, article in _ARTICLES.items():
        if key in str(url):
            return f"# {article['title']}\n\n{article['body']}\n\nSource: {url_for(key)}\n"
    digest = hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:8]
    return (
        f"# Benchmark placeholder page {digest}\n\n"
        f"The benchmark corpus has no article at {url}. Nothing here answers a "
        "question; treat it as a page that failed to provide the information.\n"
    )


def browser_transcript(instruction: str) -> str:
    """What a browser session on this instruction would have reported."""
    key = _rank(instruction)[0]
    article = _ARTICLES[key]
    return (
        f"Opened {url_for(key)}\n"
        f"Page title: {article['title']}\n"
        f"Visible text: {article['body']}\n"
        "The benchmark browser visits only the fixture corpus; no live page "
        "was loaded and no form was submitted."
    )
