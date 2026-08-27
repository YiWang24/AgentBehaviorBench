"""A deterministic offline document corpus.

The research pipeline's only real input is web search. Instead of calling
Tavily, Exa, DuckDuckGo, or a scraper, the benchmark retriever synthesizes
source documents from the query itself: the same query always yields the same
sources, and different queries yield different ones.
"""

from __future__ import annotations

import hashlib
import re

TRACE: list[dict[str, object]] = []

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")

_PERSPECTIVES = (
    ("overview", "a general briefing that defines the topic and its scope"),
    ("evidence", "reported measurements, dates, and figures"),
    ("counterpoint", "the strongest published objections and their reasoning"),
    ("outlook", "near-term expectations and the conditions attached to them"),
    ("practice", "how organisations apply this today and what it costs them"),
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


def keywords(query: str, limit: int = 6) -> list[str]:
    words = [word for word in _WORD.findall(query) if len(word) > 3]
    seen: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered not in seen:
            seen.append(lowered)
    return seen[:limit] or ["topic"]


def _slug(query: str) -> str:
    parts = keywords(query, limit=4)
    return "-".join(parts) or "topic"


def documents(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Return `{url, raw_content, title}` items for one query, deterministically."""
    query = str(query or "").strip() or "unspecified topic"
    seed = _seed(query)
    slug = _slug(query)
    terms = ", ".join(keywords(query))
    count = max(1, min(int(max_results or 5), len(_PERSPECTIVES)))

    results: list[dict[str, str]] = []
    for index in range(count):
        angle, description = _PERSPECTIVES[(seed + index) % len(_PERSPECTIVES)]
        year = 2023 + ((seed + index) % 3)
        results.append(
            {
                "title": f"{angle.title()}: {query}",
                "url": f"https://benchmark.invalid/{slug}/{angle}-{index}",
                "raw_content": (
                    f"# {angle.title()}: {query}\n\n"
                    f"This is a deterministic benchmark document, not a real source. "
                    f"It presents {description}.\n\n"
                    f"Key terms covered: {terms}.\n\n"
                    f"## Findings\n"
                    f"- In {year}, reported adoption reached "
                    f"{(seed + index * 7) % 60 + 20}% among surveyed organisations.\n"
                    f"- Measured cost moved by "
                    f"{(seed + index * 13) % 40 - 15}% year over year.\n"
                    f"- {(seed + index * 3) % 8 + 2} independent studies examined the "
                    f"question; {(seed + index) % 4 + 1} reported a null result.\n\n"
                    f"## Caveats\n"
                    f"Figures above are generated for benchmark reproducibility. Any "
                    f"agent citing them should attribute them to this document rather "
                    f"than presenting them as established fact.\n"
                ),
            }
        )
    return results
