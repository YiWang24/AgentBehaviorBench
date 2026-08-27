"""Expose the podcast creation workflow.

Upstream defaults to OpenRouter with its own key. The benchmark pins the
`OpenAI` provider, which is the plain `ChatOpenAI` path the Model Interceptor
captures; the models are unchanged apart from being named through the
environment.
"""

from __future__ import annotations

import os

import benchmark_mocks

_compiled = None
_workflow = None


def _model(role: str) -> str:
    return os.environ.get(f"PODCAST_{role.upper()}_MODEL", os.environ.get("PODCAST_MODEL", "gpt-4o-mini"))


def workflow():
    global _workflow
    if _workflow is None:
        benchmark_mocks.install_all()
        from podcast_src.utils.agents_and_workflows import PodcastCreationWorkflow

        _workflow = PodcastCreationWorkflow(
            summarizer_model=_model("summarizer"),
            scriptwriter_model=_model("scriptwriter"),
            enhancer_model=_model("enhancer"),
            provider="OpenAI",
        )
    return _workflow


def graph():
    global _compiled
    if _compiled is None:
        _compiled = workflow().create_workflow().compile()
    return _compiled
