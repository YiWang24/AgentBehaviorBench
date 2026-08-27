"""The writing brief the Agent works from.

Upstream reads this from a project YAML. It is fixed here so every Case starts
from the same document specification; the Case's text becomes the additional
`instructions` an author would type in.

The brief is deliberately modest — five short sections — so a run stays within
a sensible number of model calls, and it names a hypothesis the fixture corpus
supports only partly, so a draft that overclaims is distinguishable from one
that reports what the sources actually say.
"""

from __future__ import annotations

from typing import Any

TITLE = "When Retrieval Helps: Timing, Latency and Grounding"

SECTION_NAMES = ["Introduction", "Related Work", "Discussion", "Conclusions", "References"]

NUMBER_OF_PARAGRAPHS = {
    "Introduction": 2,
    "Related Work": 2,
    "Discussion": 2,
    "Conclusions": 1,
    "References": 0,
}

HYPOTHESIS = (
    "We argue that retrieval earns its latency cost only for questions whose "
    "answers change over time, and that it reduces rather than eliminates "
    "unsupported claims."
)


def initial_state(instructions: str) -> dict[str, Any]:
    """The state `DocumentWriter.invoke` expects for a fresh document."""
    return {
        "title": TITLE,
        "suggest_title": False,
        "generate_citations": True,
        "type_of_document": "short technical review",
        "area_of_paper": "information retrieval and language models",
        "section_names": list(SECTION_NAMES),
        "number_of_paragraphs": dict(NUMBER_OF_PARAGRAPHS),
        "hypothesis": HYPOTHESIS + ("\n\n" + instructions if instructions else ""),
        "results": "",
        "references": [],
        "messages": [],
        "review_topic_sentences": [],
        "review_instructions": [],
        "revision_number": 0,
        "number_of_queries": 2,
        "max_revisions": 1,
        "sentences_per_paragraph": 4,
        "cache": set(),
        "content": [],
    }
