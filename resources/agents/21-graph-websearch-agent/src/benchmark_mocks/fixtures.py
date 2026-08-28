"""Deterministic search results and page content.

Upstream queries Google via Serper and then scrapes whichever page the selector
picks. Neither is available offline, so both are served from a small fixture
corpus on the reserved ``benchmark.invalid`` domain. Results are ranked by
overlap with the search term, so different terms return visibly different
pages and the selector's choice is observable.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z0-9]+")

PAGES: dict[str, dict[str, str]] = {
    "planning": {
        "title": "Breaking a research question into searchable parts",
        "snippet": (
            "A research plan names the unknowns before it names the queries. "
            "Benchmark corpus notes that plans of more than seven steps are "
            "usually revised before the fourth."
        ),
        "body": (
            "Breaking a research question into searchable parts\n\n"
            "A research plan names the unknowns before it names the queries. "
            "The benchmark corpus records three habits that separate useful "
            "plans from ceremonial ones: state what you do not know, choose "
            "the cheapest source that could settle it, and stop planning once "
            "the next action is obvious. Plans longer than about seven steps "
            "were revised before the fourth step in most recorded runs."
        ),
    },
    "sources": {
        "title": "Judging whether a source answers the question",
        "snippet": (
            "Relevance is not the same as sufficiency. The benchmark corpus "
            "distinguishes pages that mention a topic from pages that settle "
            "a question about it."
        ),
        "body": (
            "Judging whether a source answers the question\n\n"
            "Relevance is not sufficiency. A page can mention every term in "
            "the query and still not settle the question. The benchmark "
            "corpus recommends asking what the page would have to say for the "
            "question to be answered, then checking whether it says it. Pages "
            "that only restate the question are recorded as near misses, and "
            "in the corpus they account for roughly half of first retrievals."
        ),
    },
    "reporting": {
        "title": "Writing a report the reader can check",
        "snippet": (
            "Name the source next to the claim rather than collecting links "
            "at the end, and say which questions the evidence did not settle."
        ),
        "body": (
            "Writing a report the reader can check\n\n"
            "A report is checkable when each claim traces to something the "
            "reader can open. The benchmark corpus recommends attaching the "
            "source to the claim rather than gathering links in a footer, and "
            "stating plainly which parts of the question the evidence left "
            "open. Reports that hide their gaps are rated lower by reviewers "
            "than reports that name them."
        ),
    },
    "revision": {
        "title": "When to search again instead of answering",
        "snippet": (
            "Reformulate when the results share the question's words but not "
            "its subject; answer when further search would only confirm."
        ),
        "body": (
            "When to search again instead of answering\n\n"
            "Reformulating helps when the results share the question's "
            "vocabulary but not its subject. It does not help when the "
            "results already agree and further search would only confirm "
            "them. The benchmark corpus notes that a second query which "
            "merely reorders the first rarely changes the result set."
        ),
    },
}

_ORDER = list(PAGES)


def url_for(key: str) -> str:
    return f"https://benchmark.invalid/articles/{key}"


def rank(query: str) -> list[str]:
    terms = set(_TOKEN.findall(str(query or "").lower()))
    scored = []
    for key in _ORDER:
        page = PAGES[key]
        words = set(_TOKEN.findall(f"{key} {page['title']} {page['body']}".lower()))
        scored.append((-len(terms & words), _ORDER.index(key), key))
    return [key for _, _, key in sorted(scored)]


def organic(query: str) -> list[dict[str, str]]:
    return [
        {"title": PAGES[key]["title"], "link": url_for(key), "snippet": PAGES[key]["snippet"]}
        for key in rank(query)
    ]


def page_body(url: str) -> str:
    for key in PAGES:
        if key in str(url):
            return PAGES[key]["body"]
    return (
        "The benchmark corpus has no page at this address. Nothing here "
        "answers a research question; treat it as a page that returned no "
        "useful content."
    )
