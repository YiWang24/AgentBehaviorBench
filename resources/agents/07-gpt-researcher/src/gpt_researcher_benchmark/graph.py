"""LangGraph entry point for the benchmark adaptation of gpt-researcher.

The upstream multi-agent research workflow is preserved: initial browsing,
plan, plan review, parallel section research, writing, fact check, diagram
generation, and publishing. Only the data layer and the writable paths change.

Import order matters. ``runtime.prepare()`` moves the process to a writable
directory and pins the retriever configuration that gpt-researcher reads from
the environment; ``benchmark_mocks.install()`` must patch the retriever and
embedding factories before the research agents are constructed.
"""

from __future__ import annotations

import copy
from typing import Any

from . import runtime

runtime.prepare()

import benchmark_mocks  # noqa: E402  (must follow runtime.prepare)

benchmark_mocks.install()

from multi_agents.agents import ChiefEditorAgent  # noqa: E402

# pdf and docx writing pulls in native rendering stacks that the slim runtime
# image does not carry, and the Judge reads the markdown report anyway.
PUBLISH_FORMATS = {"markdown": True, "pdf": False, "docx": False}

BASE_TASK: dict[str, Any] = {
    "max_sections": runtime.MAX_SECTIONS,
    "max_plan_revisions": 1,
    "max_fact_check_revisions": 1,
    "publish_formats": PUBLISH_FORMATS,
    # No websocket is attached, so human review must not block.
    "include_human_feedback": False,
    "follow_guidelines": False,
    "model": "gpt-4o",
    "guidelines": [],
    "verbose": False,
}

REPORT_KEYS = (
    "title",
    "introduction",
    "table_of_contents",
    "conclusion",
    "report",
    "fact_check_notes",
)


def build_task(query: str) -> dict[str, Any]:
    task = copy.deepcopy(BASE_TASK)
    task["query"] = query
    return task


def graph():
    """Zero-argument factory returning the compiled research workflow.

    Declared in ``langgraph.json`` so the project keeps a native LangGraph
    contract. The worker drives the pipeline through :func:`run_research`
    instead, because upstream builds a fresh ChiefEditorAgent per run to derive
    the per-run output directory and task id.
    """
    return ChiefEditorAgent(build_task(runtime.DEFAULT_QUERY)).init_research_team().compile()


async def run_research(query: str, task_id: str | None = None) -> dict[str, Any]:
    """Run the full research workflow for one query and normalize the result."""
    chief_editor = ChiefEditorAgent(build_task(query))
    state = await chief_editor.run_research_task(task_id=task_id)

    sources = state.get("sources") or []
    if not isinstance(sources, (list, tuple)):
        sources = [sources]

    sections = state.get("sections") or []
    if not isinstance(sections, (list, tuple)):
        sections = [sections]

    report = {
        key: value
        for key in REPORT_KEYS
        if isinstance(value := state.get(key), str) and value.strip()
    }
    return {
        "query": query,
        "report": report,
        "sections": [str(section) for section in sections],
        "sources": [str(source) for source in sources],
        "diagram_count": len(state.get("diagrams") or []),
    }
