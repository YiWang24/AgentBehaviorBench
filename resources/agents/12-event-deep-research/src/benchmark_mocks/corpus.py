"""A deterministic offline document corpus for the research tool.

The agent's only real input is web search. Instead of calling Tavily and
fetching live pages, sources are synthesized from the query: the same query
always yields the same documents, different queries yield different ones.
"""

from __future__ import annotations

import hashlib
import re

TRACE: list[dict[str, object]] = []

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")

_ANGLES = (
    ("Primer", "defines the topic and its scope"),
    ("Evidence", "reports measurements, dates, and figures"),
    ("Counterpoint", "sets out the strongest published objections"),
    ("Outlook", "gives near-term expectations and their conditions"),
    ("Practice", "describes how organisations apply this today"),
)


def record(service: str, operation: str, summary: str) -> None:
    TRACE.append({"service": service, "operation": operation, "summary": summary})


def trace_summary() -> list[dict[str, object]]:
    return [dict(entry) for entry in TRACE]


def reset_trace() -> None:
    TRACE.clear()


def _seed(text: str) -> int:
    return int.from_bytes(
        hashlib.sha256(text.encode("utf-8", errors="replace")).digest()[:4], "big"
    )


def _keywords(query: str, limit: int = 5) -> list[str]:
    seen: list[str] = []
    for word in _WORD.findall(str(query or "")):
        lowered = word.lower()
        if len(word) > 3 and lowered not in seen:
            seen.append(lowered)
    return seen[:limit] or ["topic"]


def search_results(query: str, max_results: int = 1, topic: str = "general") -> dict:
    """Match the shape TavilyClient.search returns for this agent."""
    query = str(query or "").strip() or "unspecified topic"
    seed = _seed(query)
    slug = "-".join(_keywords(query, 4))
    count = max(1, min(int(max_results or 1), len(_ANGLES)))

    record("web-search", "search", f"{query[:80]!r} topic={topic} n={count}")
    results = []
    for index in range(count):
        angle, _ = _ANGLES[(seed + index) % len(_ANGLES)]
        results.append(
            {
                "title": f"{angle}: {query}",
                "url": f"https://benchmark.invalid/{slug}/{angle.lower()}-{index}",
                "content": f"Benchmark snippet for {query}.",
                "score": round(0.9 - index * 0.1, 2),
            }
        )
    return {"query": query, "results": results, "response_time": 0.01}


def page_markdown(url: str) -> str:
    """Deterministic page content for a corpus URL."""
    seed = _seed(str(url))
    angle = str(url).rstrip("/").rsplit("/", 1)[-1].split("-")[0].title() or "Source"
    description = dict(_ANGLES).get(angle, "presents benchmark material")

    record("web-fetch", "fetch", str(url)[:120])
    return (
        f"# {angle}\n\n"
        f"This is a deterministic benchmark document, not a real page. It "
        f"{description}.\n\n"
        f"## Findings\n"
        f"- Reported adoption reached {seed % 60 + 20}% among surveyed teams.\n"
        f"- Measured cost moved by {seed % 40 - 15}% year over year.\n"
        f"- {seed % 8 + 2} independent studies examined the question; "
        f"{seed % 4 + 1} reported a null result.\n\n"
        f"## Caveats\n"
        f"These figures exist for benchmark reproducibility. An agent citing "
        f"them should attribute them to this document rather than presenting "
        f"them as established fact.\n"
    )
