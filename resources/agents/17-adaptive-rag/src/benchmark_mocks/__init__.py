"""Deterministic stand-ins for the Adaptive RAG graph's non-model dependencies.

Embeddings, web search, and the indexed corpus resolve locally. FAISS runs
in-process and is left alone, so the retrieval path under test is the real one.
"""

from __future__ import annotations

from .corpus import reset_trace, trace_summary
from .install import DOCUMENTS, documents, install, installed

__all__ = [
    "DOCUMENTS",
    "documents",
    "install",
    "installed",
    "reset_trace",
    "trace_summary",
]
