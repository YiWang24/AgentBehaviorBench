"""Expose the research graph with the benchmark stand-ins installed.

``create_graph`` takes the provider and model as arguments; the benchmark pins
them to the OpenAI path, which is the one the Model Interceptor captures.
"""

from __future__ import annotations

import os

import benchmark_mocks

_compiled = None

SERVER = "openai"
MODEL = os.environ.get("WEBSEARCH_MODEL", "gpt-4o")


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install()
        from agent_graph.graph import compile_workflow, create_graph

        # create_graph returns an uncompiled StateGraph; upstream compiles it
        # in a second step.
        _compiled = compile_workflow(create_graph(server=SERVER, model=MODEL))
    return _compiled
