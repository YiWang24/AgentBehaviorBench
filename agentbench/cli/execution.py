"""Shared benchmark execution for CLI command features."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from agentbench.harness import (
    BenchmarkProgress,
    ProviderSelectionError,
    SuiteAgentResult,
    SuiteConfigurationError,
    SuiteRunner,
)
from agentbench.harness.registry import AgentRegistration
from agentbench.harness.result import BenchmarkSuiteResult

from .progress import ProgressPrinter, configuration_error
from .TerminalUI import LLMActivity
from .presentation import (
    agent_view_url,
    print_agent_complete,
    print_agent_start,
    print_suite_summary,
    print_viewer_footer,
)
from .result_export import ResultLogWriter, start_result_log
from .viewer import RunningViewer

ViewerStarter = Callable[[Path], RunningViewer]


class ProgressReporter(Protocol):
    """A progress renderer that also releases any live terminal state."""

    def __call__(self, event: BenchmarkProgress) -> None:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class BenchmarkExecution:
    exit_code: int
    result: BenchmarkSuiteResult | None
    result_log: ResultLogWriter | None
    viewer: RunningViewer | None


def run_benchmark_once(
    agents: tuple[AgentRegistration, ...],
    *,
    runner: SuiteRunner,
    output_path: str | Path | None,
    output_fn: Callable[[str], None],
    viewer_starter: ViewerStarter | None,
    llm_activity: LLMActivity | None = None,
    progress: ProgressReporter | None = None,
) -> BenchmarkExecution:
    suite_id = runner.new_suite_id()
    result_log: ResultLogWriter | None = None
    viewer: RunningViewer | None = None
    if output_path is not None:
        result_log = start_result_log(
            output_path,
            suite_id=suite_id,
            selected_agent_ids=tuple(agent.agent_id for agent in agents),
        )
        if viewer_starter is not None:
            viewer = viewer_starter(result_log.path)
        output_fn(f"Suite ID: {suite_id}")
        output_fn(f"Result artifact started: {result_log.path}")
        if viewer is not None:
            output_fn(f"View: {viewer.url}")

    activity = llm_activity or LLMActivity(output_fn)
    progress_printer = progress or ProgressPrinter(output_fn, llm_activity=activity)
    try:
        try:
            result = runner.run_defuzex(
                agents,
                suite_id=suite_id,
                allow_local=True,
                track_files=False,
                on_agent_start=lambda agent, index, total: print_agent_start(
                    agent, index, total, output_fn
                ),
                on_agent_complete=lambda item: _handle_agent_complete(
                    item,
                    output_fn,
                    result_log,
                    None if viewer is None else viewer.url,
                ),
                on_progress=progress_printer,
                on_step_start=(
                    None if result_log is None else result_log.append_step_started
                ),
                on_step_complete=(
                    None if result_log is None else result_log.append_step_completed
                ),
                on_step_failure=(
                    None if result_log is None else result_log.append_step_failed
                ),
            )
        except (ProviderSelectionError, SuiteConfigurationError) as exc:
            if result_log is not None:
                result_log.append_suite_error(exc)
            output_fn(configuration_error(exc))
            if result_log is not None:
                print_viewer_footer(
                    result_log.path, None if viewer is None else viewer.url, output_fn
                )
            return BenchmarkExecution(1, None, result_log, viewer)
    finally:
        progress_printer.close()

    if result_log is not None:
        result_log.append_suite_complete(result)
    print_suite_summary(result, output_fn)
    if result_log is not None:
        print_viewer_footer(
            result_log.path, None if viewer is None else viewer.url, output_fn
        )
    return BenchmarkExecution(0 if result.passed else 1, result, result_log, viewer)


def sole_agent_result(
    result: BenchmarkSuiteResult | None, agent_id: str
) -> SuiteAgentResult | None:
    """The one Agent's result in a single-Agent suite, or None if it is not there.

    A suite that skipped anything, ran a different Agent, or ran more than one has
    not answered the question a single-Agent command asked, so there is nothing to
    read out of it.
    """

    if result is None or result.skipped_count != 0 or len(result.items) != 1:
        return None
    item = result.items[0]
    return item if item.agent_id == agent_id else None


def completed_every_case(item: SuiteAgentResult) -> bool:
    """Every requested Case ran end to end without harness errors."""

    return (
        item.error_type is None
        and item.completed_case_count == item.requested_case_count
    )


def default_result_path(
    registry_path: str | Path, command: str, agent_id: str
) -> Path:
    """Where a single-Agent command archives its Run, under `results/`.

    The Agent id reaches the filesystem here, so it is reduced to characters a
    path can carry on every platform.
    """

    repo_root = Path(registry_path).resolve().parent.parent
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", agent_id).strip("-") or "agent"
    return repo_root / "results" / f"{command}-{safe}.jsonl"


def stop_viewer(viewer: RunningViewer) -> None:
    stop = getattr(viewer, "stop", None)
    if callable(stop):
        stop()


def _handle_agent_complete(
    item: SuiteAgentResult,
    output_fn: Callable[[str], None],
    result_log: ResultLogWriter | None,
    viewer_url: str | None,
) -> None:
    print_agent_complete(item, output_fn)
    if result_log is not None:
        result_log.append_agent_complete(item)
    if viewer_url is not None:
        output_fn(f"View: {agent_view_url(viewer_url, item.agent_id)}")
