"""A deterministic offline corpus for the web-search tool.

The research assistant's only real input is DuckDuckGo. Results are synthesized
from the query, so the same query always yields the same sources.
"""

from __future__ import annotations

import hashlib
import re

TRACE: list[dict[str, object]] = []

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")

_ANGLES = ("Primer", "Evidence", "Counterpoint", "Outlook")


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


def _slug(query: str) -> str:
    words = [w.lower() for w in _WORD.findall(query) if len(w) > 3]
    return "-".join(words[:4]) or "topic"


def results(query: str, max_results: int = 4) -> list[dict[str, str]]:
    """Match the shape DuckDuckGoSearchAPIWrapper returns."""
    query = str(query or "").strip() or "unspecified topic"
    seed = _seed(query)
    slug = _slug(query)
    count = max(1, min(int(max_results or 4), len(_ANGLES)))

    record("web-search", "duckduckgo", f"{query[:80]!r} n={count}")
    return [
        {
            "snippet": (
                f"Deterministic benchmark snippet for {query}. This document "
                f"{'defines the topic' if index == 0 else 'reports findings'}: "
                f"reported adoption reached {(seed + index * 7) % 60 + 20}% and "
                f"measured cost moved by {(seed + index * 13) % 40 - 15}% year "
                f"over year. Figures exist for reproducibility, not as fact."
            ),
            "title": f"{_ANGLES[(seed + index) % len(_ANGLES)]}: {query}",
            "link": f"https://benchmark.invalid/{slug}/{index}",
            "date": "2026-01-01",
            "source": "benchmark.invalid",
        }
        for index in range(count)
    ]
