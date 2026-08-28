"""Expose Kiroku's document-writing graph.

Upstream compiles with `interrupt_before` at each manual-review node — the
human-in-the-loop points of a writing tool. The benchmark honours them and
resumes each one with an *empty* instruction, which is upstream's own
"accept as written" path: `TopicSentenceManualReview.run` and its siblings read
`config["configurable"]["instruction"]` and pass straight through when it is
blank, without a model call. No review comment is invented on the user's behalf.
"""

from __future__ import annotations

import os

import benchmark_mocks

_writer = None


def writer():
    global _writer
    if _writer is None:
        benchmark_mocks.install()
        from kiroku_app import DocumentWriter

        _writer = DocumentWriter(
            suggest_title=os.environ.get("KIROKU_SUGGEST_TITLE", "0") == "1",
            generate_citations=os.environ.get("KIROKU_GENERATE_CITATIONS", "1") == "1",
            model_name=os.environ.get("KIROKU_MODEL_NAME", "openai"),
        )
    return _writer


def graph():
    return writer().graph
