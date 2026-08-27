"""Wire the deterministic fixtures into the Adaptive RAG graph.

Three substitutions: embeddings, the web-search tool, and the document corpus
the FAISS index is built from. FAISS itself is left alone — it runs in-process,
so the retrieval path the benchmark measures is the real one.
"""

from __future__ import annotations

from langchain_core.documents import Document

from . import corpus
from .embeddings import BENCHMARK_EMBEDDINGS
from .network_guard import install as install_network_guard

_installed = False

# The indexed corpus. Retrieval is what this agent is judged on, so the
# documents carry distinguishable content rather than filler: a query about one
# of them should not rank the others equally.
DOCUMENTS: tuple[tuple[str, str], ...] = (
    (
        "retrieval-augmented-generation",
        "Retrieval-augmented generation retrieves passages from a corpus and "
        "conditions the model on them. It reduces hallucination when the "
        "corpus covers the question and degrades when it does not.",
    ),
    (
        "vector-indexes",
        "A vector index stores embeddings and answers nearest-neighbour "
        "queries. Flat indexes are exact and slow; IVF and HNSW trade recall "
        "for latency.",
    ),
    (
        "chunking",
        "Chunk size trades context against precision. Long chunks bury the "
        "answer among unrelated text; short chunks lose the surrounding "
        "context needed to interpret it.",
    ),
    (
        "evaluation",
        "Retrieval is measured with recall at k and mean reciprocal rank. "
        "Generation quality is measured separately, because a correct answer "
        "from a wrong passage is still a retrieval failure.",
    ),
)


def installed() -> bool:
    return _installed


class BenchmarkSearchResults:
    """Offline stand-in for ``TavilySearchResults``."""

    def invoke(self, query, **kwargs):
        text = query if isinstance(query, str) else str((query or {}).get("query", ""))
        found = corpus.search_results(text, 3)
        return [
            {"url": item["url"], "content": item["content"], "title": item["title"]}
            for item in found["results"]
        ]


def documents() -> list[Document]:
    """The fixture corpus, as LangChain documents."""
    return [
        Document(
            page_content=text,
            metadata={"source": f"https://benchmark.invalid/kb/{name}", "id": name},
        )
        for name, text in DOCUMENTS
    ]


def _patch_embeddings() -> None:
    from src.rag import retriever_setup

    retriever_setup.embeddings = BENCHMARK_EMBEDDINGS


def _patch_search() -> None:
    from src.rag import graph_builder

    graph_builder.TavilySearchResults = BenchmarkSearchResults


def install() -> None:
    """Install every mock, then seed the index. Idempotent."""
    global _installed
    if _installed:
        return

    _patch_embeddings()
    _patch_search()
    install_network_guard()

    # Seed FAISS after the embedding function is replaced, so the index is
    # built from deterministic vectors.
    from src.rag.retriever_setup import retriever_chain

    retriever_chain(documents())

    _installed = True
