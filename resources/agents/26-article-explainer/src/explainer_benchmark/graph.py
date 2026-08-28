"""Expose the explainer swarm.

`explainer/graph.py` builds the model and the five agents at import time and
exposes the compiled swarm as a module-level `app`, so the wrapper only has to
install the guard before importing it.

`get_chat_model` falls back to a local Ollama endpoint when `OPENAI_API_KEY` is
unset. Under the benchmark the key is always injected, so the OpenAI path is
taken; the guard would fail loudly on the Ollama fallback rather than hanging
against a port nothing is listening on.
"""

from __future__ import annotations

import benchmark_mocks

_compiled = None


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install_all()
        from explainer.graph import app

        _compiled = app
    return _compiled
