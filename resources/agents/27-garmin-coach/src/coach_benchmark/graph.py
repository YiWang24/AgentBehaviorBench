"""Expose the integrated analysis-and-planning workflow over a fixture athlete.

`create_analysis_workflow` is *not* the graph to use. It keeps unconditional
edges from `master_orchestrator` back to the three experts while the
orchestrator also routes with `Command(goto=...)`, so every orchestrator turn
re-fans out to the experts and the run never terminates; and its no-questions
branch routes to `season_planner`, a node that workflow does not contain.

`create_integrated_analysis_and_planning_workflow` is upstream's corrected
version — its own comment reads "Master orchestrator uses ONLY Command(goto=...)
for dynamic routing / NO unconditional edges from orchestrator" — and it
contains `season_planner`, so both branches resolve. It also produces the
weekly plan, which is what the athlete actually asked for.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any

import benchmark_mocks

_compiled = None


def graph():
    global _compiled
    if _compiled is None:
        benchmark_mocks.install_all()
        from services.ai.langgraph.workflows.planning_workflow import (
            create_integrated_analysis_and_planning_workflow,
        )

        _compiled = create_integrated_analysis_and_planning_workflow()
    return _compiled


def initial_state(question: str) -> dict[str, Any]:
    """Build the state the workflow expects, with the fixture athlete's data.

    `plotting_enabled` is off (matplotlib would write files the read-only image
    has nowhere to put) and `hitl_enabled` is off (the benchmark has no human
    to interrupt for).
    """
    from services.ai.langgraph.state.training_analysis_state import create_initial_state

    from . import athlete

    today = os.environ.get("COACH_TODAY", "2026-08-24")
    parsed = _dt.date.fromisoformat(today)
    return create_initial_state(
        user_id="benchmark",
        athlete_name=athlete.ATHLETE_NAME,
        garmin_data=athlete.garmin_data(),
        analysis_context=question,
        competitions=athlete.COMPETITIONS,
        current_date={"date": today, "weekday": parsed.strftime("%A")},
        execution_id="benchmark-run",
        plotting_enabled=False,
        hitl_enabled=False,
    )
