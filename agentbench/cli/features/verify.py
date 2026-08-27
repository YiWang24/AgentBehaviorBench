"""Verify one Agent starts and is observable, without any DefuzeX credentials."""

from __future__ import annotations

import shutil
import sys
import tempfile
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from agentbench.harness import BenchmarkSuiteResult, SuiteAgentResult
from agentbench.harness.offline import DEFAULT_PROBE_TEXT, probe_inputs
from agentbench.harness.registry import AgentRegistration, load_registry
from agentbench.runtime.agentcontainer import runtime_type
from agentbench.runtime.interception import (
    DEFAULT_TRACE_MAX_BYTES,
    InterceptionConfig,
)

from agentbench.cli.environment import load_project_environment
from agentbench.cli.execution import BenchmarkExecution, run_benchmark_once
from agentbench.cli.offline_runtime import OfflineRuntime, build_offline_runtime
from agentbench.cli.TerminalUI import LLMActivity
from agentbench.cli.verify_report import (
    ERROR,
    FAIL,
    PASS,
    VerifyProgress,
    VerifyReport,
    print_header,
    print_report,
)

from .base import CommandFeature
from .run import DEFAULT_REGISTRY_PATH

DEFAULT_INPUT_COUNT = 1
ARTIFACT_PREFIX = "agentbench-verify-"
INPUT_FILE_MARKER = "@"


def configure_parser(parser: ArgumentParser) -> None:
    parser.add_argument("agent_id", help="Registered Agent to verify.")
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="Load host defaults from PATH instead of .env.",
    )
    parser.add_argument(
        "--input",
        metavar="TEXT",
        help=(
            "Probe text sent to the Agent, or @PATH to read it from a file. "
            "Defaults to a short generic prompt."
        ),
    )
    parser.add_argument(
        "--inputs",
        type=int,
        default=DEFAULT_INPUT_COUNT,
        metavar="N",
        help="Number of probe inputs to send. Defaults to 1.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the temporary result log instead of deleting it on exit.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Print one JSON summary instead of the human report.",
    )
    parser.add_argument(
        "--llm-trace",
        choices=("off", "terminal"),
        default="off",
        help="Print the sanitized model requests and responses that were captured.",
    )
    parser.add_argument(
        "--llm-trace-max-bytes",
        type=int,
        default=DEFAULT_TRACE_MAX_BYTES,
        metavar="BYTES",
        help="Maximum captured payload bytes per request or response.",
    )


def execute(args: Namespace) -> int:
    load_project_environment(args.env_file)
    kwargs: dict[str, object] = {
        "input_count": args.inputs,
        "keep_artifacts": args.keep_artifacts,
    }
    if args.as_json:
        kwargs["as_json"] = True
    if args.input is not None:
        kwargs["probe_text"] = _probe_text(args.input)
    if args.llm_trace != "off":
        kwargs["llm_trace"] = args.llm_trace
    if args.llm_trace_max_bytes != DEFAULT_TRACE_MAX_BYTES:
        kwargs["llm_trace_max_bytes"] = args.llm_trace_max_bytes
    return verify(args.agent_id, **kwargs)


def verify(
    agent_id: str,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    probe_text: str = DEFAULT_PROBE_TEXT,
    input_count: int = DEFAULT_INPUT_COUNT,
    keep_artifacts: bool = False,
    output_fn: Callable[[str], None] = print,
    offline: OfflineRuntime | None = None,
    llm_trace: str = "off",
    llm_trace_max_bytes: int = DEFAULT_TRACE_MAX_BYTES,
    as_json: bool = False,
) -> int:
    """Start one Agent offline and confirm its model traffic is observable.

    Nothing here reads ``DEFUZEX_API_KEY`` or ``OPENROUTER_API_KEY``, contacts a
    network, or writes the Registry. A pass means the adapter and runtime are
    healthy; it says nothing about benchmark quality.
    """

    # In JSON mode nothing may reach stdout before the document itself.
    stage_output = _discard if as_json else output_fn

    agent, rejection = _select_agent(agent_id, registry_path, input_count)
    if agent is None:
        return _fail_early(agent_id, rejection, output_fn, as_json=as_json)

    print_header(agent_id, stage_output)
    # The live panel is wanted on a terminal, but its non-interactive fallback would
    # duplicate what the sectioned report already prints, so that path is silenced.
    llm_activity = LLMActivity(
        _discard,
        live_updates=not as_json and sys.stdout.isatty(),
    )
    report = _run_verification(
        agent=agent,
        offline=offline
        or build_offline_runtime(
            max_inputs=input_count,
            probes=probe_inputs(probe_text, count=input_count),
            output_fn=stage_output,
            llm_trace=llm_trace,
            llm_trace_max_bytes=llm_trace_max_bytes,
            activity_sink=llm_activity,
        ),
        llm_activity=llm_activity,
        stage_output=stage_output,
        keep_artifacts=keep_artifacts,
    )

    if as_json:
        output_fn(report.to_json())
    else:
        output_fn("")
        print_report(report, output_fn)
    return report.exit_code


def _select_agent(
    agent_id: str, registry_path: str | Path, input_count: int
) -> tuple[AgentRegistration | None, str]:
    """Resolve the Agent, or explain why verification cannot run at all."""

    if input_count < 1:
        return None, "--inputs must be at least 1"
    try:
        # Disabled Agents are verifiable on purpose: this is the check you run while
        # adapting, before an Agent is ever enabled for a batch.
        agent = load_registry(registry_path).find(agent_id, enabled_only=False)
    except (KeyError, ValueError) as exc:
        # str(KeyError) re-quotes its argument, which would leak into the report.
        return None, str(exc.args[0] if exc.args else exc)

    rejection = _preflight_error(agent)
    return (None, rejection) if rejection else (agent, "")


def _run_verification(
    *,
    agent: AgentRegistration,
    offline: OfflineRuntime,
    llm_activity: LLMActivity,
    stage_output: Callable[[str], None],
    keep_artifacts: bool,
) -> VerifyReport:
    """Run the single Case and summarize it, cleaning up unless asked not to."""

    artifact_dir = Path(tempfile.mkdtemp(prefix=ARTIFACT_PREFIX))
    try:
        execution = run_benchmark_once(
            # One Case keeps verification about startup, not benchmark coverage.
            (replace(agent, case_count=1),),
            runner=offline.runner,
            output_path=artifact_dir / f"verify-{_safe_name(agent.agent_id)}.jsonl",
            output_fn=_discard,  # the sectioned report owns all verify output
            viewer_starter=None,
            llm_activity=llm_activity,
            progress=VerifyProgress(
                stage_output,
                llm_activity=llm_activity,
                call_count=lambda: offline.captured_pair_count,
            ),
        )
        return _build_report(
            agent_id=agent.agent_id,
            execution=execution,
            offline=offline,
            keep_artifacts=keep_artifacts,
        )
    finally:
        if not keep_artifacts:
            shutil.rmtree(artifact_dir, ignore_errors=True)


def _build_report(
    *,
    agent_id: str,
    execution: BenchmarkExecution,
    offline: OfflineRuntime,
    keep_artifacts: bool,
) -> VerifyReport:
    """Turn the suite outcome into a startup verdict."""

    result = execution.result
    log_path = (
        execution.result_log.path
        if keep_artifacts and execution.result_log is not None
        else None
    )
    common: dict[str, object] = {
        "agent_id": agent_id,
        "captured_pairs": offline.captured_pair_count,
        "substituted_secrets": offline.substituted_secrets,
        "result_log": log_path,
        "calls": offline.calls,
    }
    item = _agent_item(result, agent_id)
    if item is not None:
        common.update(
            completed_cases=item.completed_case_count,
            requested_cases=item.requested_case_count,
        )

    if item is None or not _started(item):
        reason = "Agent did not complete startup"
        if item is not None and item.error_type is not None:
            reason = f"{item.error_type}: {item.error_message}"
        return VerifyReport(
            verdict=FAIL,
            reason=reason,
            **common,  # type: ignore[arg-type]
        )

    if offline.captured_pair_count < 1:
        return VerifyReport(
            verdict=FAIL,
            reason="Agent ran but no model call was captured, so its LLM traffic is not observable",
            **common,  # type: ignore[arg-type]
        )

    return VerifyReport(verdict=PASS, **common)  # type: ignore[arg-type]


def _fail_early(
    agent_id: str,
    reason: str,
    output_fn: Callable[[str], None],
    *,
    as_json: bool,
) -> int:
    report = VerifyReport(agent_id=agent_id, verdict=ERROR, reason=reason)
    if as_json:
        output_fn(report.to_json())
    else:
        output_fn(f"Verification error: {reason}")
    return 2


def _agent_item(
    result: BenchmarkSuiteResult | None, agent_id: str
) -> SuiteAgentResult | None:
    if result is None or result.skipped_count != 0 or len(result.items) != 1:
        return None
    item = result.items[0]
    return item if item.agent_id == agent_id else None


def _started(item: SuiteAgentResult) -> bool:
    """Startup succeeded when the single Case ran end to end without harness errors."""

    return (
        item.error_type is None
        and item.completed_case_count == item.requested_case_count
    )


def _discard(_: str) -> None:
    """Swallow shared-execution chatter that the verify report replaces."""


def _agent_started(result: BenchmarkSuiteResult, agent_id: str) -> bool:
    """Startup succeeded when the single Case ran end to end without harness errors."""

    if result.skipped_count != 0 or len(result.items) != 1:
        return False
    item = result.items[0]
    return (
        item.agent_id == agent_id
        and item.error_type is None
        and item.completed_case_count == item.requested_case_count
    )


def _preflight_error(agent: AgentRegistration) -> str | None:
    """Reject Agents that cannot answer the question verification asks."""

    selected = runtime_type(agent.path)
    if selected != "docker":
        return (
            f"Agent '{agent.agent_id}' uses the {selected!r} runtime. Offline "
            "verification requires the Docker runtime so model traffic can be "
            "intercepted."
        )
    if InterceptionConfig.from_agent_dir(agent.path) is None:
        return (
            f"Agent '{agent.agent_id}' declares no [llm_interception] section, so "
            "its model calls cannot be captured or served offline."
        )
    return None


def _probe_text(value: str) -> str:
    if not value.startswith(INPUT_FILE_MARKER):
        return value
    return Path(value[len(INPUT_FILE_MARKER) :]).expanduser().read_text(
        encoding="utf-8"
    )


def _safe_name(agent_id: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in agent_id
    ).strip("-")
    return cleaned or "agent"


FEATURE = CommandFeature(
    name="verify",
    help="Check offline that one Agent starts and its model traffic is captured.",
    description=(
        "Start one registered Agent with network egress blocked and locally "
        "generated model replies, then confirm it responds and that every model "
        "call is captured. Uses no DefuzeX or provider credentials and never "
        "changes the Registry."
    ),
    configure=configure_parser,
    execute=execute,
)
