"""LangGraph entry point for the benchmark adaptation of open-deepthink's QDAD.

QDAD treats language as a latent: it derives a noun/verb basis from the prompt,
builds an N x N grid of agents over that basis, adds qualitative noise, denoises
the grid over several rounds, and synthesises a final answer.

The repository also ships a QNN pipeline and a distillation graph; the benchmark
selects the QDAD graph, which is the one that reaches nothing but the model.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from langchain_openai import ChatOpenAI  # noqa: E402

from deepthink.qdad.graph import build_qdad_graph  # noqa: E402

RECURSION_LIMIT = 40

_graph = None


def _llm():
    return ChatOpenAI(model=runtime.MODEL, temperature=0)


def graph():
    """Zero-argument factory returning the compiled QDAD graph."""
    global _graph
    if _graph is None:
        _graph = build_qdad_graph(_llm())
    return _graph


async def run_diffusion(prompt: str, run_config: dict | None = None) -> dict[str, Any]:
    """Run one qualitative diffusion and normalize the public result."""
    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)

    state = await graph().ainvoke(
        {
            "user_prompt": prompt,
            "n": runtime.GRID_SIZE,
            "denoising_steps": runtime.DENOISING_STEPS,
            "noise_temperature": 1.0,
            "noun_verb_temperature": 0.7,
        },
        config=config,
    )

    solution = state.get("final_solution")
    if hasattr(solution, "model_dump"):
        solution = solution.model_dump()

    return {
        "prompt": prompt,
        "solution": solution if isinstance(solution, dict) else {"text": str(solution or "")},
        "build_prompt": state.get("app_build_prompt") or "",
        "nouns": list(state.get("nouns") or []),
        "verbs": list(state.get("verbs") or []),
        "grid_size": runtime.GRID_SIZE,
        "denoising_steps": runtime.DENOISING_STEPS,
    }
