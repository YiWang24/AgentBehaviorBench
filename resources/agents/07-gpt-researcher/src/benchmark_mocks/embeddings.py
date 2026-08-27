"""Deterministic local embeddings.

gpt-researcher defaults to ``openai:text-embedding-3-small`` and uses the
vectors only to rank and compress retrieved context — they never reach the
agent's visible output. The Model Interceptor has no embeddings protocol and
OpenRouter exposes no embeddings endpoint, so that traffic cannot be captured
or forwarded. Rather than let it escape to a live provider, embeddings are
computed locally from a hash of the text.

The mapping is a hashed bag of words: deterministic, order-independent per
term, and similar texts share terms and therefore direction, which is enough
for the ranking and compression the pipeline performs.
"""

from __future__ import annotations

import hashlib
import math
import re

DIMENSIONS = 256

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _vector(text: str) -> list[float]:
    values = [0.0] * DIMENSIONS
    tokens = _TOKEN.findall(str(text or "").lower()) or ["empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        values[index] += sign
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0.0:
        return [0.0] * DIMENSIONS
    return [value / norm for value in values]


class BenchmarkEmbeddings:
    """LangChain ``Embeddings``-compatible deterministic implementation."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return _vector(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


BENCHMARK_EMBEDDINGS = BenchmarkEmbeddings()
