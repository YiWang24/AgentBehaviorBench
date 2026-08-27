"""LangGraph entry point for the benchmark adaptation of the langtalks SWE agent.

The upstream graph is imported unchanged: the architect researches the project
and produces an implementation plan, then the developer applies it with the
file, search, and codemap tools.
"""

from __future__ import annotations

from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from agent.graph import swe_agent as _graph  # noqa: E402

RECURSION_LIMIT = 60


def graph():
    """Zero-argument factory returning the compiled SWE agent."""
    return _graph


def _plan_summary(plan: Any) -> dict[str, Any]:
    if plan is None:
        return {}
    dump = getattr(plan, "model_dump", None)
    return dump() if callable(dump) else {"plan": str(plan)}


async def run_task(task: str, run_config: dict | None = None) -> dict[str, Any]:
    """Run the agent against the fixture project and normalize the result."""
    from benchmark_mocks.workspace import snapshot

    config: dict[str, Any] = dict(run_config or {})
    config.setdefault("recursion_limit", RECURSION_LIMIT)

    root = runtime.workspace()
    before = snapshot(root)

    state = await _graph.ainvoke(
        {"implementation_research_scratchpad": [{"role": "user", "content": task}]},
        config=config,
    )

    after = snapshot(root)
    changed = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )

    plan = state.get("implementation_plan") if isinstance(state, dict) else None
    messages = (state or {}).get("implementation_research_scratchpad") or []

    return {
        "task": task,
        "implementation_plan": _plan_summary(plan),
        "changed_files": changed,
        "message_count": len(messages),
        "files": sorted(after),
    }
