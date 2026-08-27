"""Build the patent-drafting graph.

Upstream wires the agent bundle inside `_build_draft_graph_for_runtime` in
`api/routers.py`. That module imports FastAPI at module scope, so it cannot be
imported here; the one factory the benchmark needs is reproduced below with the
same bundle, the same retry policies, and the same stub fallbacks (copied
verbatim into `stubs.py`).

`build_llm_callable` routes an `openai`/`qwen`/`kimi`/`deepseek`/`minimax`/`glm`
provider through an OpenAI-compatible endpoint, which the Model Interceptor
captures. When no key is supplied it returns None and the bundle falls back to
the deterministic stubs — upstream's own behaviour — so the graph is runnable
either way.
"""

from __future__ import annotations

import os

import benchmark_mocks

_compiled = None


def _llm_runtime() -> dict:
    return {
        "provider": os.environ.get("MCUBE_PROVIDER", "openai"),
        "model": os.environ.get("MCUBE_MODEL", "gpt-4o"),
        "vision_model": os.environ.get("MCUBE_VISION_MODEL", os.environ.get("MCUBE_MODEL", "gpt-4o")),
        "base_url": os.environ.get("MCUBE_BASE_URL") or None,
        "temperature": float(os.environ.get("MCUBE_TEMPERATURE", "0.3")),
    }


def _build():
    from agents.base_agent import BaseStructuredAgent, RetryPolicy
    from models.draft_schemas import (
        ClaimTraceabilityReport,
        ClaimsSet,
        ClaimsSetRevision,
        Specification,
        TechSummary,
    )
    from models.image_schemas import DrawingMap
    from models.review_schemas import ReviewReport
    from services.checkpoint import CheckpointManager
    from services.llm_factory import build_llm_callable
    from workflows.draft_workflow import DraftAgentBundle, build_draft_workflow

    from .stubs import _DRAFT_STUBS, _make_stub_llm_callable, _minimal_specification_stub

    runtime = _llm_runtime()
    llm_callable = build_llm_callable(
        provider=runtime["provider"],
        model=runtime["model"],
        vision_model=runtime["vision_model"],
        base_url=runtime["base_url"],
        api_key=os.environ.get("MCUBE_API_KEY"),
        temperature=runtime["temperature"],
    )

    def agent(cls, name, stub):
        return BaseStructuredAgent[cls](
            name=name,
            llm_callable=llm_callable or _make_stub_llm_callable(stub),
            retry_policy=RetryPolicy(max_retries=3),
        )

    bundle = DraftAgentBundle(
        extract_tech_agent=agent(TechSummary, "extract_tech_agent", _DRAFT_STUBS["extract_tech"]),
        draft_claims_agent=agent(ClaimsSet, "draft_claims_agent", _DRAFT_STUBS["draft_claims"]),
        revise_claims_agent=agent(ClaimsSetRevision, "revise_claims_agent", _DRAFT_STUBS["revise_claims"]),
        drawing_analyzer_agent=agent(DrawingMap, "drawing_analyzer_agent", _DRAFT_STUBS["drawing_map"]),
        traceability_agent=agent(ClaimTraceabilityReport, "traceability_agent", _DRAFT_STUBS["traceability"]),
        logic_review_agent=agent(ReviewReport, "logic_review_agent", _DRAFT_STUBS["logic_review"]),
        write_spec_agent=agent(Specification, "write_spec_agent", _minimal_specification_stub()),
    )
    return build_draft_workflow(bundle, checkpointer=CheckpointManager().checkpointer)


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install_all()
        _compiled = _build()
    return _compiled
